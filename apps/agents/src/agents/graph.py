"""Assemble and compile the GraphRAG Reel agent graph with memory."""

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import RetryPolicy

from agents.nodes import generate, router
from agents.state import AgentState
from agents.tools import TOOLS

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.store.base import BaseStore


def build_graph(
    checkpointer: "BaseCheckpointSaver | None" = None,
    store: "BaseStore | None" = None,
) -> "CompiledStateGraph":
    """Build and compile the GraphRAG agent.

    Flow: START -> router -> (tools -> router)* -> generate -> END.
    Compiled WITHOUT a checkpointer by default so LangGraph Studio can supply
    its own; the backend (Phase 5) passes Postgres checkpointer + store.
    """
    builder = StateGraph(AgentState)
    builder.add_node(
        "router",
        router,
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_node(
        "generate",
        generate,
        retry_policy=RetryPolicy(max_attempts=3),
    )

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        tools_condition,
        {"tools": "tools", END: "generate"},
    )
    builder.add_edge("tools", "router")
    builder.add_edge("generate", END)
    return builder.compile(checkpointer=checkpointer, store=store)


graph = build_graph()
