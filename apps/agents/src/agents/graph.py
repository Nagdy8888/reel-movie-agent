"""Assemble and compile the deterministic hybrid GraphRAG Reel agent."""

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.nodes import converse, generate, retrieve, route
from agents.state import AgentState

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.store.base import BaseStore


def _next_after_route(state: AgentState) -> str:
    """Pick the branch for the routed intent.

    Chitchat/greetings go straight to a conversational reply; everything else
    (factual lookups and recommendations) goes through grounded retrieval.

    Args:
        state: The current agent state after routing.

    Returns:
        The name of the next node: ``converse`` or ``retrieve``.
    """
    return "converse" if state.get("intent") == "chitchat" else "retrieve"


def build_graph(
    checkpointer: "BaseCheckpointSaver | None" = None,
    store: "BaseStore | None" = None,
) -> "CompiledStateGraph":
    """Build and compile the deterministic hybrid GraphRAG agent.

    Flow: START -> route -> (converse | retrieve -> generate) -> END.
    `route` classifies the turn's intent. Greetings/small talk branch to
    `converse` (a friendly, graph-free reply) so the agent no longer answers
    "no information" to a hello. Factual and recommendation turns branch to
    `retrieve`, which runs LightRAG local and hybrid context-only retrieval and,
    for empty recommendation turns, falls back to top box-office projection
    movies. It then merges and reranks candidates, recovers stable movie keys,
    and hydrates UI artifacts from Supabase. `generate` produces the grounded,
    fail-closed answer. Compiled WITHOUT a checkpointer by default so LangGraph
    Studio can supply its own; the backend passes a Postgres checkpointer + store.
    """
    builder = StateGraph(AgentState)
    builder.add_node(
        "route",
        route,
        retry_policy=RetryPolicy(max_attempts=3),
    )
    builder.add_node(
        "converse",
        converse,
        retry_policy=RetryPolicy(max_attempts=3),
    )
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

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route",
        _next_after_route,
        {"converse": "converse", "retrieve": "retrieve"},
    )
    builder.add_edge("converse", END)
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)
    return builder.compile(checkpointer=checkpointer, store=store)


graph = build_graph()
