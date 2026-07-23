"""Chat endpoint that delegates resilient SSE orchestration to a service."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.auth import current_user
from api.deps import ChatStoreDep, GraphDep, SettingsDep, UserDep
from api.limiter import get_authenticated_user_id, limiter
from api.schemas import ChatRequest
from api.services.streaming import ChatStreamService, ThreadOwnershipError

router = APIRouter(tags=["chat"], dependencies=[Depends(current_user)])


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-sent chat tokens, artifacts, errors, and completion events.",
            "content": {"text/event-stream": {}},
        }
    },
)
@limiter.limit("20/minute")
@limiter.limit("20/minute", key_func=get_authenticated_user_id)
async def chat(
    request: Request,
    body: ChatRequest,
    graph: GraphDep,
    user: UserDep,
    store: ChatStoreDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Stream one authenticated movie-chat turn over server-sent events."""
    service = ChatStreamService(graph, store, settings, request)
    try:
        stream = await service.start(body, user.id)
    except ThreadOwnershipError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Thread not owned by user") from exc
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
