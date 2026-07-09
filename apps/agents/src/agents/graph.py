"""Assemble and compile the deterministic hybrid GraphRAG Reel agent."""

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.nodes import generate, retrieve
from agents.state import AgentState

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.store.base import BaseStore


def build_graph(
    checkpointer: "BaseCheckpointSaver | None" = None,
    store: "BaseStore | None" = None,
) -> "CompiledStateGraph":
    """Build and compile the deterministic hybrid GraphRAG agent.

    Flow: START -> retrieve -> generate -> END.
    `retrieve` always runs both retrievers (robust Text2Cypher + hybrid
    vector/full-text semantic search with graph expansion), then merges and
    reranks the candidates into grounding context. `generate` is the only node
    that produces user-facing text and is grounded + fail-closed. Compiled
    WITHOUT a checkpointer by default so LangGraph Studio can supply its own;
    the backend (Phase 5) passes a Postgres checkpointer + store.
    """
    builder = StateGraph(AgentState)
    builder.add_node(
        "retrieve",
        retrieve,
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "generate",
        generate,
        retry_policy=RetryPolicy(max_attempts=3),
    )

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)
    return builder.compile(checkpointer=checkpointer, store=store)


graph = build_graph()
