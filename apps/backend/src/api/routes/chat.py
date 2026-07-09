"""Chat endpoint that streams the agent's answer over SSE."""

import json
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from starlette.concurrency import iterate_in_threadpool

from api.deps import GraphDep
from api.schemas import ChatRequest

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


async def _event_stream(graph, body: ChatRequest):
    """Yield SSE frames for streamed answer tokens.

    Reads chat_model token events from stream_events v3 and forwards content.
    Sync iteration runs in a thread pool so the event loop stays responsive and
    the sync Postgres checkpointer works on all platforms (Windows included).
    """
    thread_id = body.thread_id or str(uuid.uuid4())
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "run_name": "reel-chat",
        "tags": ["graphrag"],
        "metadata": {"thread_id": thread_id},
    }
    inputs = {"messages": [HumanMessage(content=body.message)]}
    yield f"event: meta\ndata: {json.dumps({'thread_id': thread_id})}\n\n"
    stream = graph.stream_events(inputs, config, version="v3")
    async for raw in iterate_in_threadpool(stream):
        text = _token_from_v3_event(raw)
        if text:
            yield f"data: {json.dumps({'token': text})}\n\n"
    yield "event: done\ndata: {}\n\n"


@router.post("/chat")
async def chat(body: ChatRequest, graph: GraphDep) -> StreamingResponse:
    """Stream an answer to the user's movie question via the agent graph."""
    return StreamingResponse(
        _event_stream(graph, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
