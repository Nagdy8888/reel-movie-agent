"""Pydantic request/response models for the backend API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A chat request from the client."""

    message: str = Field(description="The user's movie question.", min_length=1, max_length=2000)
    thread_id: str | None = Field(
        default=None, description="Conversation id for memory; server generates one if absent."
    )


class HealthResponse(BaseModel):
    """Health/readiness response."""

    status: str = Field(description="'ok' or 'degraded'.")
    detail: str = Field(default="", description="Optional detail message.")


class MessageOut(BaseModel):
    """A single stored chat message."""

    role: str = Field(description="'user' or 'assistant'.")
    content: str = Field(description="Message text.")
    created_at: datetime = Field(description="When the message was stored.")


class ConversationSummary(BaseModel):
    """A conversation without its messages (for list views)."""

    id: UUID = Field(description="Conversation id.")
    thread_id: str = Field(description="LangGraph thread id backing this chat.")
    title: str | None = Field(
        default=None, description="Short title derived from the first message."
    )
    created_at: datetime = Field(description="Creation time.")
    updated_at: datetime = Field(description="Last activity time.")


class ConversationDetail(ConversationSummary):
    """A conversation with its ordered messages."""

    messages: list[MessageOut] = Field(description="Messages in chronological order.")
