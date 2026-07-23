"""Retrieval functions + tools for the deterministic hybrid GraphRAG agent."""

from __future__ import annotations

import json
from dataclasses import dataclass

from agents import retrieval
from agents.async_bridge import run_sync
from agents.clients import get_utility_llm
from agents.prompts.system import RERANK_SYSTEM_V1
from agents.settings import get_settings

MAX_CANDIDATE_CHARS = 2_500


@dataclass(frozen=True)
class RerankOutcome:
    """Result and degradation details from one reranking attempt."""

    candidates: list[str]
    used_model: bool
    error_type: str | None = None


def strip_code_fences(text: str) -> str:
    """Remove optional markdown code fences around LLM output.

    Args:
        text: Raw LLM output that may wrap JSON in triple backticks.

    Returns:
        The inner text with fences removed.
    """
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


def run_local_context(question: str) -> str:
    """Retrieve structured movie context via LightRAG local mode.

    Args:
        question: The user's natural-language question.

    Returns:
        Retrieved context, or an empty string if nothing was found.
    """
    return run_sync(retrieval.query_local_context(question))


def run_semantic_search(question: str) -> list[str]:
    """Answer a fuzzy/plot/theme question via LightRAG hybrid retrieval.

    Args:
        question: The user's natural-language question.

    Returns:
        A list of context passages (possibly empty).
    """
    return run_sync(retrieval.query_hybrid_context(question))


def run_recommendation_fallback(limit: int | None = None) -> list[str]:
    """Return top box-office movies as fallback recommendation context.

    Used only when a recommendation request matched nothing specific, so the
    agent can still suggest real movies from the projection instead of failing
    closed.

    Args:
        limit: Maximum number of movies to return. Defaults to the configured
            ``retrieval_top_k`` when not provided.

    Returns:
        A list of movie neighbourhood strings (possibly empty).
    """
    return run_sync(retrieval.recommendation_fallback(limit))


def run_projection_grounding(movie_ids: list[str]) -> list[str]:
    """Load typed cast/genre/year facts for recovered movie keys.

    Args:
        movie_ids: Projection ``movie:{wikipedia_id}`` keys.

    Returns:
        Formatted grounding passages to prepend before LightRAG context.
    """
    return run_sync(retrieval.projection_grounding_for_movies(movie_ids))


def run_rerank(question: str, candidates: list[str]) -> RerankOutcome:
    """Reorder candidates by relevance to the question, keeping the top-k.

    Fail-open: on any LLM or parse error the original candidates are returned
    truncated to ``rerank_top_k``, so reranking can never block an answer.

    Args:
        question: The user's natural-language question.
        candidates: Retrieved context passages to reorder.

    Returns:
        Selected passages plus whether model ranking succeeded and an optional
        sanitized error type.
    """
    settings = get_settings()
    if not candidates:
        return RerankOutcome(candidates=[], used_model=False)
    bounded = [candidate[:MAX_CANDIDATE_CHARS] for candidate in candidates]
    numbered = "\n\n".join(f"[{i}] {chunk}" for i, chunk in enumerate(bounded))
    prompt = RERANK_SYSTEM_V1.format(
        top_k=settings.rerank_top_k,
        question=question,
        candidates=numbered,
    )
    try:
        raw = strip_code_fences(str(get_utility_llm().invoke(prompt).content))
        order = json.loads(raw)
        picked = [candidates[i] for i in order if isinstance(i, int) and 0 <= i < len(candidates)]
        if picked:
            return RerankOutcome(
                candidates=picked[: settings.rerank_top_k],
                used_model=True,
            )
        return RerankOutcome(
            candidates=candidates[: settings.rerank_top_k],
            used_model=False,
            error_type="InvalidRerankSelection",
        )
    except Exception as exc:
        return RerankOutcome(
            candidates=candidates[: settings.rerank_top_k],
            used_model=False,
            error_type=type(exc).__name__,
        )
