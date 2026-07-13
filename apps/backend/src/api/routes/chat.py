"""Chat endpoint that streams the agent's answer over SSE and persists history."""

import json
import uuid
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from agents.artifacts import (
    GraphArtifact,
    SourceArtifact,
    filter_artifacts_by_answer,
)
from api.deps import ChatStoreDep, GraphDep, UserDep
from api.limiter import limiter
from api.schemas import ChatRequest
from api.services.chats import ChatStore
from api.services.titles import PLACEHOLDER_TITLE, generate_conversation_title

router = APIRouter(tags=["chat"])


# Nodes whose streamed tokens are user-facing answer text. `generate` emits
# grounded answers; `converse` emits the friendly reply for greetings/small
# talk. The router and retrievers use a non-streaming utility LLM, so they never
# reach this path.
_ANSWER_NODES = ("generate", "converse")


def _token_from_v3_event(raw: dict) -> str:
    """Extract a streamed text token from a LangGraph v3 ``messages`` event."""
    if raw.get("method") != "messages":
        return ""
    data = raw.get("params", {}).get("data")
    if not isinstance(data, tuple) or len(data) != 2:
        return ""
    payload, metadata = data
    if metadata.get("langgraph_node") not in _ANSWER_NODES:
        return ""
    if payload.get("event") != "content-block-delta":
        return ""
    delta = payload.get("delta", {})
    if delta.get("type") != "text-delta":
        return ""
    return str(delta.get("text", ""))


def _artifacts_from_v3_event(
    raw: dict,
) -> tuple[list[SourceArtifact], GraphArtifact] | None:
    """Extract sources/graph from a LangGraph v3 ``values`` event after retrieve."""
    if raw.get("method") != "values":
        return None
    data = raw.get("params", {}).get("data")
    if not isinstance(data, dict) or "sources" not in data:
        return None
    sources = data.get("sources")
    graph = data.get("graph")
    if not isinstance(sources, list) or not isinstance(graph, dict):
        return None
    return cast(list[SourceArtifact], sources), cast(GraphArtifact, graph)


async def _event_stream(
    graph,
    body: ChatRequest,
    user_id: str,
    thread_id: str,
    conversation_id: str,
    store: ChatStore,
    *,
    is_new_thread: bool,
):
    """Yield SSE frames for streamed answer tokens and persist the assistant reply.

    Sync iteration runs in a thread pool so the event loop stays responsive and
    the sync Postgres checkpointer/store work on all platforms (Windows included).
    """
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "run_name": "reel-chat",
        "tags": ["graphrag"],
        "metadata": {"thread_id": thread_id, "user_id": user_id},
    }
    inputs = {"messages": [HumanMessage(content=body.message)]}
    meta = json.dumps({"thread_id": thread_id, "conversation_id": conversation_id})
    yield f"event: meta\ndata: {meta}\n\n"
    parts: list[str] = []
    artifacts_emitted = False
    initial_context: str | None = None
    last_sources: list[SourceArtifact] = []
    last_graph: GraphArtifact = {"nodes": [], "links": []}
    stream = graph.stream_events(inputs, config, version="v3")
    async for raw in iterate_in_threadpool(stream):
        if raw.get("method") == "values":
            data = raw.get("params", {}).get("data")
            if isinstance(data, dict):
                context = str(data.get("context", ""))
                if initial_context is None:
                    initial_context = context
                elif not artifacts_emitted and context != initial_context:
                    artifacts = _artifacts_from_v3_event(raw)
                    if artifacts is not None:
                        sources, graph_data = artifacts
                        last_sources = sources
                        last_graph = graph_data
                        yield f"event: sources\ndata: {json.dumps({'sources': sources})}\n\n"
                        yield f"event: graph\ndata: {json.dumps(graph_data)}\n\n"
                        artifacts_emitted = True
        text = _token_from_v3_event(raw)
        if text:
            parts.append(text)
            yield f"data: {json.dumps({'token': text})}\n\n"
    answer = "".join(parts)
    if answer and last_sources:
        filtered = filter_artifacts_by_answer(last_sources, last_graph, answer)
        if filtered["sources"] != last_sources or filtered["graph"] != last_graph:
            yield f"event: sources\ndata: {json.dumps({'sources': filtered['sources']})}\n\n"
            yield f"event: graph\ndata: {json.dumps(filtered['graph'])}\n\n"
    if answer:
        await run_in_threadpool(store.add_message, conversation_id, "assistant", answer)
        await run_in_threadpool(store.touch, conversation_id)
        if is_new_thread:
            title = await run_in_threadpool(
                generate_conversation_title, body.message, answer[:400]
            )
            await run_in_threadpool(store.update_title, conversation_id, title)
    yield "event: done\ndata: {}\n\n"


@router.post("/chat")
@limiter.limit("20/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    graph: GraphDep,
    user: UserDep,
    store: ChatStoreDep,
) -> StreamingResponse:
    """Stream an answer to the authenticated user's movie question and persist it."""
    thread_id = body.thread_id or str(uuid.uuid4())
    is_new_thread = body.thread_id is None
    conversation = await run_in_threadpool(
        store.upsert_conversation,
        user.id,
        thread_id,
        PLACEHOLDER_TITLE if is_new_thread else body.message[:60],
    )
    if conversation is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Thread not owned by user")
    await run_in_threadpool(store.add_message, conversation["id"], "user", body.message)
    return StreamingResponse(
        _event_stream(
            graph,
            body,
            user.id,
            thread_id,
            str(conversation["id"]),
            store,
            is_new_thread=is_new_thread,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
