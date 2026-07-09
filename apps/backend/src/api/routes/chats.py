"""User chat history endpoints (list, fetch, delete)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from starlette.concurrency import run_in_threadpool

from api.auth import current_user
from api.deps import ChatStoreDep, UserDep
from api.schemas import ConversationDetail, ConversationSummary

router = APIRouter(prefix="/chats", tags=["chats"], dependencies=[Depends(current_user)])


@router.get("", response_model=list[ConversationSummary])
async def list_chats(user: UserDep, store: ChatStoreDep) -> list[ConversationSummary]:
    """List the authenticated user's conversations, newest first."""
    rows = await run_in_threadpool(store.list_for_user, user.id)
    return [ConversationSummary(**row) for row in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_chat(
    conversation_id: UUID, user: UserDep, store: ChatStoreDep
) -> ConversationDetail:
    """Return one conversation with its messages; 404 if not owned."""
    row = await run_in_threadpool(store.get_for_user, user.id, str(conversation_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return ConversationDetail(**row)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    conversation_id: UUID, user: UserDep, store: ChatStoreDep
) -> Response:
    """Delete a conversation and its messages; 404 if not owned."""
    ok = await run_in_threadpool(store.delete_for_user, user.id, str(conversation_id))
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
