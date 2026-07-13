"""Tests for batched movie embedding preparation."""

from __future__ import annotations

import pytest

from ingestion.build_index import (
    MAX_OVERVIEW_CHARS,
    _batches,
    _compose_document,
    _safe_index_name,
    _token_count,
)


def test_compose_document_includes_rich_graph_context_and_bounds_overview() -> None:
    """Embedding text should contain all supported context within its bound."""
    row = {
        "title": "Example",
        "year": 2024,
        "tagline": "A test movie",
        "overview": "x" * (MAX_OVERVIEW_CHARS + 100),
        "genres": ["Drama"],
        "keywords": ["friendship"],
        "cast": ["Actor as Hero", None],
        "directors": ["Director"],
        "writers": ["Writer"],
    }

    document = _compose_document(row)

    assert document.startswith("Example (2024)")
    assert "Genres: Drama" in document
    assert "Keywords: friendship" in document
    assert "Starring: Actor as Hero" in document
    assert "x" * MAX_OVERVIEW_CHARS in document
    assert "x" * (MAX_OVERVIEW_CHARS + 1) not in document


def test_embedding_batches_preserve_order() -> None:
    """Embedding work should be grouped without dropping rows."""
    rows = [{"tmdbId": index} for index in range(5)]

    assert list(_batches(rows, 3)) == [rows[:3], rows[3:]]
    with pytest.raises(ValueError, match="positive"):
        list(_batches(rows, -1))


def test_token_count_uses_embedding_model_tokenizer() -> None:
    """Token accounting should return the exact sum for all documents."""
    assert _token_count(["hello", "world"], "text-embedding-3-small") == 2


def test_index_names_reject_cypher_fragments() -> None:
    """Index identifiers from settings should not permit Cypher injection."""
    assert _safe_index_name("movie_plot_embeddings") == "movie_plot_embeddings"
    with pytest.raises(ValueError, match="Invalid"):
        _safe_index_name("movie-index; DROP DATABASE neo4j")
