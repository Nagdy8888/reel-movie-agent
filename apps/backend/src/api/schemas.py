"""Pydantic request/response models for the backend API."""

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
