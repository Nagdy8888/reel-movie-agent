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
        default=None, description="Short LLM-generated title summarizing the conversation."
    )
    created_at: datetime = Field(description="Creation time.")
    updated_at: datetime = Field(description="Last activity time.")


class ConversationDetail(ConversationSummary):
    """A conversation with its ordered messages."""

    messages: list[MessageOut] = Field(description="Messages in chronological order.")


class SourceOut(BaseModel):
    """A cited movie source for the right pane."""

    id: str = Field(description="Stable source id.")
    title: str = Field(description="Movie title.")
    subtitle: str | None = Field(default=None, description="Optional tagline or subtitle.")
    year: str | None = Field(default=None, description="Release year when known.")
    poster_url: str | None = Field(default=None, description="Optional movie poster image URL.")
    tags: list[str] = Field(default_factory=list, description="Cast/director tags.")


class GraphNodeOut(BaseModel):
    """A node in the explored knowledge subgraph."""

    id: str = Field(description="Stable node id.")
    label: str = Field(description="Display label.")
    type: str = Field(description="Node label type, e.g. Movie or Person.")


class GraphLinkOut(BaseModel):
    """A relationship edge in the explored knowledge subgraph."""

    source: str = Field(description="Source node id.")
    target: str = Field(description="Target node id.")
    label: str = Field(description="Relationship label.")


class GraphOut(BaseModel):
    """Subgraph explored during retrieval."""

    nodes: list[GraphNodeOut] = Field(default_factory=list, description="Graph nodes.")
    links: list[GraphLinkOut] = Field(default_factory=list, description="Graph edges.")
