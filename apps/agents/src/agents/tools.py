"""Retrieval functions + tools for the deterministic hybrid GraphRAG agent."""

from __future__ import annotations

import json
import re

from langchain_core.tools import BaseTool, tool

from agents import retrieval
from agents.async_bridge import run_sync
from agents.clients import get_utility_llm
from agents.prompts.system import RERANK_SYSTEM_V1
from agents.settings import get_settings

MAX_CANDIDATE_CHARS = 2_500
_CODE_FENCE = re.compile(r"^```(?:\w+)?\n([\s\S]*?)\n```$", re.MULTILINE)


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


def run_graph_query(question: str) -> str:
    """Answer a structured question via LightRAG local context retrieval.

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


def run_rerank(question: str, candidates: list[str]) -> list[str]:
    """Reorder candidates by relevance to the question, keeping the top-k.

    Fail-open: on any LLM or parse error the original candidates are returned
    truncated to ``rerank_top_k``, so reranking can never block an answer.

    Args:
        question: The user's natural-language question.
        candidates: Retrieved context passages to reorder.

    Returns:
        The most relevant passages, best first, at most ``rerank_top_k``.
    """
    settings = get_settings()
    if not candidates:
        return []
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
        picked = [bounded[i] for i in order if isinstance(i, int) and 0 <= i < len(bounded)]
        if picked:
            return picked[: settings.rerank_top_k]
    except (ValueError, TypeError):
        pass
    return bounded[: settings.rerank_top_k]


@tool
def graph_query(question: str) -> str:
    """Answer a structured movie question via LightRAG local retrieval.

    Use for precise facts: who acted in a movie, release years, box office,
    cast/character lookups.
    """
    return run_graph_query(question) or "No results."


@tool
def semantic_search(question: str) -> str:
    """Answer a fuzzy/plot/theme movie question via LightRAG hybrid retrieval.

    Use for questions about what a movie is *about* rather than exact facts.
    """
    return "\n\n".join(run_semantic_search(question)) or "No results."


TOOLS: list[BaseTool] = [graph_query, semantic_search]
