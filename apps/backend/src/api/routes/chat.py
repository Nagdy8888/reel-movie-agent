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


def _answer_node_message(raw: dict) -> tuple[object, dict] | None:
    """Return the ``(payload, metadata)`` of an answer-node ``messages`` event.

    Returns ``None`` when the event is not a v3 ``messages`` frame produced by an
    answer node (``generate``/``converse``).
    """
    if raw.get("method") != "messages":
        return None
    data = raw.get("params", {}).get("data")
    if not isinstance(data, tuple) or len(data) != 2:
        return None
    payload, metadata = data
    if metadata.get("langgraph_node") not in _ANSWER_NODES:
        return None
    return payload, metadata


def _token_from_v3_event(raw: dict) -> str:
    """Extract a streamed text token from a LangGraph v3 ``messages`` event.

    Only streamed LLM output arrives as ``content-block-delta`` dicts. Statically
    built replies (the fail-closed empty-context answer) arrive as a whole
    message object in a single frame; those are handled by
    ``_final_text_from_v3_event`` and skipped here (guarding against calling
    ``.get`` on a message object).
    """
    message = _answer_node_message(raw)
    if message is None:
        return ""
    payload, _metadata = message
    if not isinstance(payload, dict):
        return ""
    if payload.get("event") != "content-block-delta":
        return ""
    delta = payload.get("delta", {})
    if delta.get("type") != "text-delta":
        return ""
    return str(delta.get("text", ""))


def _message_text(content: object) -> str:
    """Flatten LangChain message ``content`` (str or content blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _final_text_from_v3_event(raw: dict) -> str:
    """Extract a complete answer from a ``messages`` frame carrying a full message.

    Answer nodes that return a pre-built reply without calling the LLM (the
    fail-closed empty-context answer) emit the whole ``AIMessage`` in one frame
    instead of ``content-block-delta`` chunks. Surface its text so the turn still
    produces a visible, persisted answer instead of crashing or ending silently.
    Streamed deltas (dict payloads) are ignored here.
    """
    message = _answer_node_message(raw)
    if message is None:
        return ""
    payload, _metadata = message
    if isinstance(payload, dict):
        return ""
    return _message_text(getattr(payload, "content", None))


def _artifacts_from_v3_event(
    raw: dict,
) -> tuple[list[SourceArtifact], GraphArtifact] | None:
    """Extract sources/graph from a LangGraph v3 ``values`` event.

    Returns the artifacts whenever a values snapshot carries both keys with the
    right types — including empty values. Empty snapshots must be surfaced so the
    caller can reset artifacts a prior turn left in the checkpointed state; if we
    dropped them, stale sources/graph would leak into the next turn's stream.
    Returns ``None`` only when the event is not an artifact-bearing values frame.
    """
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
    # The checkpointer persists `sources`/`graph` across turns, so early values
    # snapshots on a resumed thread still carry the *previous* turn's artifacts.
    # Track the freshest snapshot instead of trusting the first non-empty one,
    # and flush it only once the answer starts streaming — by then `retrieve`
    # has run and overwritten any stale artifacts for this turn.
    artifacts_flushed = False
    have_artifacts = False
    last_sources: list[SourceArtifact] = []
    last_graph: GraphArtifact = {"nodes": [], "links": []}
    fallback_answer = ""

    def _artifact_frames() -> list[str]:
        return [
            f"event: sources\ndata: {json.dumps({'sources': last_sources})}\n\n",
            f"event: graph\ndata: {json.dumps(last_graph)}\n\n",
        ]

    stream = graph.stream_events(inputs, config, version="v3")
    async for raw in iterate_in_threadpool(stream):
        artifacts = _artifacts_from_v3_event(raw)
        if artifacts is not None:
            last_sources, last_graph = artifacts
            have_artifacts = True
        whole = _final_text_from_v3_event(raw)
        if whole:
            fallback_answer = whole
        text = _token_from_v3_event(raw)
        if text:
            if not artifacts_flushed and have_artifacts:
                for frame in _artifact_frames():
                    yield frame
                artifacts_flushed = True
            parts.append(text)
            yield f"data: {json.dumps({'token': text})}\n\n"
    # Flush artifacts even when no answer token streamed (e.g. fail-closed reply)
    # so a non-empty result still populates the panels.
    if not artifacts_flushed and have_artifacts and (
        last_sources or last_graph.get("nodes") or last_graph.get("links")
    ):
        for frame in _artifact_frames():
            yield frame
        artifacts_flushed = True
    answer = "".join(parts)
    # Some replies are returned as a whole message rather than streamed token by
    # token (the fail-closed empty-context answer). Emit that text once so the UI
    # shows it and it gets persisted, instead of ending the turn silently.
    if not answer and fallback_answer:
        yield f"data: {json.dumps({'token': fallback_answer})}\n\n"
        answer = fallback_answer
    if answer and last_sources:
        filtered = filter_artifacts_by_answer(
            last_sources,
            last_graph,
            answer,
            question=body.message,
        )
        if filtered["sources"] != last_sources or filtered["graph"] != last_graph:
            yield f"event: sources\ndata: {json.dumps({'sources': filtered['sources']})}\n\n"
            yield f"event: graph\ndata: {json.dumps(filtered['graph'])}\n\n"
    if answer:
        await run_in_threadpool(store.add_message, conversation_id, "assistant", answer)
        await run_in_threadpool(store.touch, conversation_id)
        if is_new_thread:
            title = await run_in_threadpool(generate_conversation_title, body.message, answer[:400])
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
