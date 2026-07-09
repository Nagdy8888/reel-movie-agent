"""State schema for the Reel agent graph."""

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Conversation state.

    messages: full chat history. Reducer `add_messages` appends new messages
        instead of overwriting, so each node can return only its new message(s).
    intent: routed intent for the current turn (``factual``, ``recommend`` or
        ``chitchat``). Overwritten each turn (last-write-wins); drives which
        branch of the graph runs.
    context: merged, reranked grounding text for the current turn. Overwritten
        each turn (last-write-wins) because it is derived fresh from retrieval.
    sources: structured movie cards for the current turn's right pane.
    graph: person–movie subgraph explored during retrieval for the current turn.
    errors: non-fatal retrieval/generation issues, kept for observability.
        Reducer `operator.add` appends so nodes never clobber prior entries.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    intent: str
    context: str
    sources: list[dict[str, Any]]
    graph: dict[str, Any]
    errors: Annotated[list[str], operator.add]


class RouteUpdate(TypedDict):
    """State update produced by the `route` node."""

    intent: str


class RetrieveUpdate(TypedDict):
    """State update produced by the `retrieve` node."""

    context: str
    sources: list[dict[str, Any]]
    graph: dict[str, Any]
    errors: list[str]


class GenerateUpdate(TypedDict):
    """State update produced by the `generate` node."""

    messages: list[AnyMessage]
