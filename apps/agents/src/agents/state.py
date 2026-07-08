"""State schema for the Reel agent graph."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Conversation state.

    messages: full chat history. Reducer `add_messages` appends new messages
        instead of overwriting, so each node can return only its new message(s).
    """

    messages: Annotated[list[AnyMessage], add_messages]


class RouterUpdate(TypedDict):
    """State update produced by the `router` node."""

    messages: list[AnyMessage]


class GenerateUpdate(TypedDict):
    """State update produced by the `generate` node."""

    messages: list[AnyMessage]
