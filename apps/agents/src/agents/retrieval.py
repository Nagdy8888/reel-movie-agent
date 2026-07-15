"""Async LightRAG retrieval facade used by sync tool wrappers."""

from __future__ import annotations

from agents.lightrag_service import aquery_context
from agents.projection import (
    fetch_cast_names,
    fetch_top_box_office_movies,
    format_movie_context,
    format_projection_grounding,
)
from agents.settings import get_settings


async def query_local_context(question: str) -> str:
    """Retrieve structured/fact-oriented context via LightRAG local mode.

    Args:
        question: Natural-language user question.

    Returns:
        A joined context string (possibly empty).
    """
    return await aquery_context(question, mode="local")


async def query_hybrid_context(question: str) -> list[str]:
    """Retrieve thematic/plot context via LightRAG hybrid mode.

    Args:
        question: Natural-language user question.

    Returns:
        A single-item list containing the context string when non-empty,
        otherwise an empty list (matches the prior semantic-search shape).
    """
    context = await aquery_context(question, mode="hybrid")
    return [context] if context else []


async def recommendation_fallback(limit: int | None = None) -> list[str]:
    """Return top box-office movies from the Supabase projection.

    Args:
        limit: Maximum movies; defaults to ``retrieval_top_k``.

    Returns:
        Formatted movie neighbourhood strings for the generate node.
    """
    settings = get_settings()
    top_k = limit if limit is not None else settings.retrieval_top_k
    movies = fetch_top_box_office_movies(top_k)
    cast_map = fetch_cast_names(
        [m["id"] for m in movies],
        limit_per_movie=12,
        include_characters=True,
    )
    return [format_movie_context(movie, cast=cast_map.get(movie["id"], [])) for movie in movies]


async def projection_grounding_for_movies(movie_ids: list[str]) -> list[str]:
    """Return typed projection facts for recovered movie keys.

    Args:
        movie_ids: ``movie:{wikipedia_id}`` keys from retrieval artifacts.

    Returns:
        Formatted grounding blocks (cast/genres/year/box office).
    """
    return format_projection_grounding(movie_ids)
