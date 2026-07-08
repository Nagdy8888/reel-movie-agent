"""Assemble and compile the minimal Reel agent graph."""

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.nodes import respond
from agents.state import AgentState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


def build_graph() -> "CompiledStateGraph":
    """Build and compile the agent graph.

    A single `respond` node wired START -> respond -> END. Later phases add
    retrieval nodes and a checkpointer.
    """
    builder = StateGraph(AgentState)
    builder.add_node(
        "respond",
        respond,
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    return builder.compile()


graph = build_graph()
