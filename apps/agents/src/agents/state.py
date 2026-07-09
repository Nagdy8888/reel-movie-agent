"""State schema for the Reel agent graph."""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Conversation state.

    messages: full chat history. Reducer `add_messages` appends new messages
        instead of overwriting, so each node can return only its new message(s).
    context: merged, reranked grounding text for the current turn. Overwritten
        each turn (last-write-wins) because it is derived fresh from retrieval.
    errors: non-fatal retrieval/generation issues, kept for observability.
        Reducer `operator.add` appends so nodes never clobber prior entries.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    context: str
    errors: Annotated[list[str], operator.add]


class RetrieveUpdate(TypedDict):
    """State update produced by the `retrieve` node."""

    context: str
    errors: list[str]


class GenerateUpdate(TypedDict):
    """State update produced by the `generate` node."""

    messages: list[AnyMessage]
