"""Nodes for the deterministic hybrid GraphRAG Reel agent."""

from typing import Any, cast

from langchain_core.messages import AIMessage, SystemMessage

from agents.artifacts import build_retrieval_artifacts
from agents.clients import get_chat_model, get_utility_llm
from agents.prompts.system import (
    CONVERSE_SYSTEM_V1,
    EMPTY_CONTEXT_REPLY,
    GENERATE_SYSTEM_V3,
    ROUTER_SYSTEM_V1,
)
from agents.state import AgentState, GenerateUpdate, RetrieveUpdate, RouteUpdate
from agents.tools import (
    run_graph_query,
    run_recommendation_fallback,
    run_rerank,
    run_semantic_search,
)

VALID_INTENTS = ("factual", "recommend", "chitchat")
MAX_GENERATION_CONTEXT_CHARS = 14_000


def _latest_question(state: AgentState) -> str:
    """Return the most recent human message text from the conversation.

    Args:
        state: The current agent state.

    Returns:
        The latest human message content, or an empty string if none exists.
    """
    for message in reversed(state["messages"]):
        if message.type == "human":
            return str(message.content)
    return ""


def route(state: AgentState) -> RouteUpdate:
    """Classify the latest turn so the graph can branch on intent.

    Reads from state:  messages
    Writes to state:   intent
    Side effects:      one non-streaming utility LLM call (classification only)
    Failure mode:      defaults to "factual" so an unclassifiable turn still
                       goes through grounded, fail-closed retrieval.
    """
    question = _latest_question(state)
    if not question:
        return {"intent": "chitchat"}
    try:
        raw = str(get_utility_llm().invoke(ROUTER_SYSTEM_V1.format(question=question)).content)
    except Exception:
        return {"intent": "factual"}
    label = raw.strip().lower()
    for intent in VALID_INTENTS:
        if intent in label:
            return {"intent": intent}
    return {"intent": "factual"}


def retrieve(state: AgentState) -> RetrieveUpdate:
    """Run both retrievers, merge, and rerank into grounding context.

    Reads from state:  messages, intent
    Writes to state:   context, sources, graph, errors
    Side effects:      LightRAG context retrieval (RAG Postgres + local/hybrid
                       query) and one non-streaming rerank LLM call; projection
                       reads for artifact hydration
    Failure mode:      returns {"context": "", "errors": [...]} on retrieval
                       failure so `generate` fails closed (never fabricates).
                       For a `recommend` turn that matched nothing, falls back
                       to top box-office movies so open-ended requests still
                       yield real suggestions.
    """
    question = _latest_question(state)
    errors: list[str] = []
    if not question:
        return {
            "context": "",
            "sources": [],
            "graph": {"nodes": [], "links": []},
            "errors": ["retrieve: no user question found"],
        }

    candidates: list[str] = []
    try:
        graph_facts = run_graph_query(question)
        if graph_facts:
            candidates.append(f"[Graph facts]\n{graph_facts}")
    except Exception as exc:
        errors.append(f"graph_query: {exc}")

    try:
        candidates.extend(run_semantic_search(question))
    except Exception as exc:
        errors.append(f"semantic_search: {exc}")

    if not candidates and state.get("intent") == "recommend":
        try:
            candidates = run_recommendation_fallback()
        except Exception as exc:
            errors.append(f"recommendation_fallback: {exc}")

    try:
        candidates = run_rerank(question, candidates)
    except Exception as exc:
        errors.append(f"rerank: {exc}")

    artifacts = build_retrieval_artifacts(candidates)
    if candidates and not artifacts["sources"]:
        errors.append("retrieve: no projection movie recovered from context")
        candidates = []
    return {
        "context": "\n\n".join(candidates)[:MAX_GENERATION_CONTEXT_CHARS],
        "sources": cast(list[dict[str, Any]], artifacts["sources"]),
        "graph": cast(dict[str, Any], artifacts["graph"]),
        "errors": errors,
    }


def converse(state: AgentState) -> GenerateUpdate:
    """Reply to greetings/small talk without touching the movie graph.

    Reads from state:  messages
    Writes to state:   messages (final AI answer)
    Side effects:      one streaming OpenAI call
    Failure mode:      relies on the node RetryPolicy; the prompt forbids
                       asserting any specific movie fact, so no fabrication.
    """
    model = get_chat_model()
    system = SystemMessage(content=CONVERSE_SYSTEM_V1)
    reply = model.invoke([system, *state["messages"]])
    return {"messages": [reply]}


def generate(state: AgentState) -> GenerateUpdate:
    """Produce the final grounded answer with citations (fail-closed).

    Reads from state:  messages, context
    Writes to state:   messages (final AI answer)
    Side effects:      one streaming OpenAI call when retrieval context exists
    Failure mode:      if no context was retrieved, answers EMPTY_CONTEXT_REPLY
                       rather than fabricating (no LLM call).
    """
    context = state.get("context", "")
    if not context.strip():
        return {"messages": [AIMessage(content=EMPTY_CONTEXT_REPLY)]}

    model = get_chat_model()
    system = SystemMessage(content=GENERATE_SYSTEM_V3.format(context=context))
    reply = model.invoke([system, *state["messages"]])
    return {"messages": [reply]}
