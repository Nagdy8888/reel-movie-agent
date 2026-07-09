"""Chat endpoint that streams the agent's answer over SSE and persists history."""

import json
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from api.deps import ChatStoreDep, GraphDep, UserDep
from api.limiter import limiter
from api.schemas import ChatRequest
from api.services.chats import ChatStore

router = APIRouter(tags=["chat"])


def _token_from_v3_event(raw: dict) -> str:
    """Extract a streamed text token from a LangGraph v3 ``messages`` event."""
    if raw.get("method") != "messages":
        return ""
    data = raw.get("params", {}).get("data")
    if not isinstance(data, tuple) or len(data) != 2:
        return ""
    payload, metadata = data
    if metadata.get("langgraph_node") != "generate":
        return ""
    if payload.get("event") != "content-block-delta":
        return ""
    delta = payload.get("delta", {})
    if delta.get("type") != "text-delta":
        return ""
    return str(delta.get("text", ""))


async def _event_stream(
    graph,
    body: ChatRequest,
    user_id: str,
    thread_id: str,
    conversation_id: str,
    store: ChatStore,
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
    stream = graph.stream_events(inputs, config, version="v3")
    async for raw in iterate_in_threadpool(stream):
        text = _token_from_v3_event(raw)
        if text:
            parts.append(text)
            yield f"data: {json.dumps({'token': text})}\n\n"
    answer = "".join(parts)
    if answer:
        await run_in_threadpool(store.add_message, conversation_id, "assistant", answer)
        await run_in_threadpool(store.touch, conversation_id)
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
    conversation = await run_in_threadpool(
        store.upsert_conversation, user.id, thread_id, body.message[:60]
    )
    if conversation is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Thread not owned by user")
    await run_in_threadpool(store.add_message, conversation["id"], "user", body.message)
    return StreamingResponse(
        _event_stream(graph, body, user.id, thread_id, str(conversation["id"]), store),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
