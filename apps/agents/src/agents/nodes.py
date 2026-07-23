"""Nodes for the deterministic hybrid GraphRAG Reel agent."""

import logging
import re
from typing import Any, cast

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langsmith import get_current_run_tree

from agents.artifacts import build_retrieval_artifacts, title_mentioned_in_text
from agents.clients import get_chat_model, get_utility_llm
from agents.prompts.system import (
    CONVERSE_SYSTEM_V1,
    EMPTY_CONTEXT_REPLY,
    GENERATE_SYSTEM_V3,
    ROUTER_SYSTEM_V1,
)
from agents.state import AgentState, GenerateUpdate, RetrieveUpdate, RouteUpdate
from agents.tools import (
    run_local_context,
    run_projection_grounding,
    run_recommendation_fallback,
    run_rerank,
    run_semantic_search,
)

VALID_INTENTS = ("factual", "recommend", "chitchat")
MAX_GENERATION_CONTEXT_CHARS = 14_000
_MOVIE_CITATION = re.compile(r"\[(movie:\d+)\]")
logger = logging.getLogger("reel.agent")


def _thread_id(config: RunnableConfig | None) -> str:
    """Return the current LangGraph thread identifier for correlation."""
    configurable = (config or {}).get("configurable", {})
    value = configurable.get("thread_id") if isinstance(configurable, dict) else None
    return str(value) if value else "uncheckpointed"


def _add_trace_metadata(**metadata: object) -> None:
    """Attach sanitized node outcomes to the active LangSmith run."""
    try:
        run_tree = get_current_run_tree()
    except Exception:
        return
    if run_tree is not None:
        run_tree.metadata.update(metadata)


def _error_code(stage: str, exc: Exception) -> str:
    """Return a stable error code without leaking exception details."""
    return f"{stage}:{type(exc).__name__}"


def _bounded_context(candidates: list[str]) -> str:
    """Join ranked context without cutting a passage in the middle.

    Oversized candidates are split only at blank-line passage boundaries.
    An individual passage larger than the full budget is omitted.
    """
    selected: list[str] = []
    used = 0
    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned:
            continue
        passages = (
            [cleaned]
            if len(cleaned) <= MAX_GENERATION_CONTEXT_CHARS
            else [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        )
        for passage in passages:
            if len(passage) > MAX_GENERATION_CONTEXT_CHARS:
                continue
            addition = len(passage) + (2 if selected else 0)
            if used + addition > MAX_GENERATION_CONTEXT_CHARS:
                return "\n\n".join(selected)
            selected.append(passage)
            used += addition
    return "\n\n".join(selected)


def _grounding_failure(answer: str, sources: list[dict[str, Any]]) -> str | None:
    """Return why a generated answer fails stable-source citation checks."""
    if answer.strip() == EMPTY_CONTEXT_REPLY:
        return None
    citations = _MOVIE_CITATION.findall(answer)
    if not citations:
        return "missing_citation"
    by_id = {str(source.get("id")): str(source.get("title", "")) for source in sources}
    if any(citation not in by_id for citation in citations):
        return "unsupported_citation"
    if any(not title_mentioned_in_text(by_id[citation], answer) for citation in citations):
        return "citation_title_mismatch"
    return None


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


def _fresh_turn(intent: str) -> RouteUpdate:
    """Build a route update that also clears the prior turn's artifacts.

    The checkpointer persists ``context``/``sources``/``graph`` across turns.
    Resetting them here guarantees each turn starts clean: `retrieve` repopulates
    them for factual/recommend turns, while `chitchat` turns (which skip
    retrieval) correctly surface no movie cards or subgraph instead of the
    previous answer's.

    Args:
        intent: Exact routing label for the latest user turn.

    Returns:
        A route update with all per-turn derived state reset.
    """
    return {
        "intent": intent,
        "context": "",
        "sources": [],
        "graph": {"nodes": [], "links": []},
        "errors": [],
    }


def route(state: AgentState, config: RunnableConfig | None = None) -> RouteUpdate:
    """Classify the latest turn so the graph can branch on intent.

    Reads from state:  messages
    Writes to state:   intent, context, sources, graph (artifacts reset per turn)
    Side effects:      one non-streaming utility LLM call (classification only)
    Failure mode:      defaults to "factual" so an unclassifiable turn still
                       goes through grounded, fail-closed retrieval.
    """
    thread_id = _thread_id(config)
    question = _latest_question(state)
    if not question:
        logger.info(
            "agent route completed",
            extra={"thread_id": thread_id, "intent": "chitchat", "reason": "empty_question"},
        )
        return _fresh_turn("chitchat")
    try:
        raw = str(get_utility_llm().invoke(ROUTER_SYSTEM_V1.format(question=question)).content)
    except Exception as exc:
        error_code = _error_code("route", exc)
        logger.warning(
            "agent route degraded",
            extra={"thread_id": thread_id, "intent": "factual", "error": error_code},
        )
        _add_trace_metadata(route_intent="factual", route_error=error_code)
        return _fresh_turn("factual")
    label = raw.strip().lower()
    if label in VALID_INTENTS:
        logger.info(
            "agent route completed",
            extra={"thread_id": thread_id, "intent": label, "classifier_output": label},
        )
        _add_trace_metadata(route_intent=label, route_classifier_output=label)
        return _fresh_turn(label)
    logger.warning(
        "agent route defaulted",
        extra={"thread_id": thread_id, "intent": "factual", "classifier_output": label},
    )
    _add_trace_metadata(route_intent="factual", route_classifier_output=label)
    return _fresh_turn("factual")


def retrieve(state: AgentState, config: RunnableConfig | None = None) -> RetrieveUpdate:
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
    thread_id = _thread_id(config)
    question = _latest_question(state)
    errors: list[str] = []
    if not question:
        error_code = "retrieve:MissingQuestion"
        logger.warning(
            "agent retrieval failed closed",
            extra={"thread_id": thread_id, "reason": error_code},
        )
        _add_trace_metadata(retrieval_errors=[error_code], retrieval_status="failed_closed")
        return {
            "context": "",
            "sources": [],
            "graph": {"nodes": [], "links": []},
            "errors": [error_code],
        }

    candidates: list[str] = []
    local_hits = 0
    hybrid_hits = 0
    fallback_hits = 0
    try:
        graph_facts = run_local_context(question)
        if graph_facts:
            candidates.append(f"[Graph facts]\n{graph_facts}")
            local_hits = 1
    except Exception as exc:
        errors.append(_error_code("local_context", exc))

    try:
        semantic_candidates = run_semantic_search(question)
        hybrid_hits = len(semantic_candidates)
        candidates.extend(semantic_candidates)
    except Exception as exc:
        errors.append(_error_code("hybrid_context", exc))

    if not candidates and state.get("intent") == "recommend":
        try:
            candidates = run_recommendation_fallback()
            fallback_hits = len(candidates)
        except Exception as exc:
            errors.append(_error_code("recommendation_fallback", exc))

    rerank = run_rerank(question, candidates)
    candidates = rerank.candidates
    if rerank.error_type:
        errors.append(f"rerank:{rerank.error_type}")

    artifacts = build_retrieval_artifacts(candidates, question=question)
    if candidates and not artifacts["sources"]:
        errors.append("projection_recovery:NoMovie")
        candidates = []
    elif artifacts["sources"]:
        # LightRAG plot entities are often characters; inject typed cast/genres
        # from the Supabase projection so "who starred in …" is answerable.
        try:
            movie_ids = [str(source["id"]) for source in artifacts["sources"]]
            projection_blocks = run_projection_grounding(movie_ids)
            if projection_blocks:
                candidates = [
                    "[Projection facts]\n" + "\n\n".join(projection_blocks),
                    *candidates,
                ]
        except Exception as exc:
            errors.append(_error_code("projection_grounding", exc))
    retrieval_status = "failed_closed" if not candidates else ("degraded" if errors else "healthy")
    logger_method = logger.warning if errors else logger.info
    logger_method(
        "agent retrieval completed",
        extra={
            "thread_id": thread_id,
            "status": retrieval_status,
            "local_hits": local_hits,
            "hybrid_hits": hybrid_hits,
            "fallback_hits": fallback_hits,
            "rerank_used_model": rerank.used_model,
            "candidate_count": len(candidates),
            "source_count": len(artifacts["sources"]),
            "error_count": len(errors),
            "errors": errors,
        },
    )
    _add_trace_metadata(
        retrieval_status=retrieval_status,
        retrieval_local_hits=local_hits,
        retrieval_hybrid_hits=hybrid_hits,
        retrieval_fallback_hits=fallback_hits,
        retrieval_rerank_used_model=rerank.used_model,
        retrieval_source_count=len(artifacts["sources"]),
        retrieval_errors=errors,
    )
    return {
        "context": _bounded_context(candidates),
        "sources": cast(list[dict[str, Any]], artifacts["sources"]),
        "graph": cast(dict[str, Any], artifacts["graph"]),
        "errors": errors,
    }


def converse(state: AgentState, config: RunnableConfig | None = None) -> GenerateUpdate:
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
    logger.info("agent conversation completed", extra={"thread_id": _thread_id(config)})
    return {"messages": [reply]}


def generate(state: AgentState, config: RunnableConfig | None = None) -> GenerateUpdate:
    """Produce the final grounded answer with citations (fail-closed).

    Reads from state:  messages, context
    Writes to state:   messages (final AI answer)
    Side effects:      one streaming OpenAI call when retrieval context exists
    Failure mode:      if no context was retrieved, answers EMPTY_CONTEXT_REPLY
                       rather than fabricating (no LLM call).
    """
    context = state.get("context", "")
    thread_id = _thread_id(config)
    errors = state.get("errors", [])
    if not context.strip():
        logger.warning(
            "agent generation failed closed",
            extra={"thread_id": thread_id, "reason": "empty_context", "errors": errors},
        )
        _add_trace_metadata(generation_status="failed_closed", generation_reason="empty_context")
        return {"messages": [AIMessage(content=EMPTY_CONTEXT_REPLY)]}

    model = get_chat_model()
    system_content = GENERATE_SYSTEM_V3.format(context=context)
    if errors:
        system_content += (
            "\n\nSome retrieval stages were unavailable. Use only the context "
            "that is present and begin with 'Based on the available movie data,' "
            "without exposing internal error details."
        )
    system = SystemMessage(content=system_content)
    reply = model.invoke([system, *state["messages"]])
    answer = reply.content if isinstance(reply.content, str) else ""
    grounding_failure = _grounding_failure(answer, state.get("sources", []))
    if grounding_failure:
        logger.warning(
            "agent generation failed grounding check",
            extra={"thread_id": thread_id, "reason": grounding_failure},
        )
        _add_trace_metadata(
            generation_status="failed_closed",
            generation_reason=grounding_failure,
        )
        return {"messages": [AIMessage(content=EMPTY_CONTEXT_REPLY)]}
    status = "degraded" if errors else "healthy"
    logger.info(
        "agent generation completed",
        extra={
            "thread_id": thread_id,
            "status": status,
            "context_chars": len(context),
            "source_count": len(state.get("sources", [])),
        },
    )
    _add_trace_metadata(generation_status=status)
    return {"messages": [reply]}
