"""Unit tests for the LightRAG retrieval facade wrappers."""

from types import SimpleNamespace

import pytest

from agents import tools


@pytest.mark.asyncio
async def test_query_modes_delegate_to_lightrag(monkeypatch) -> None:
    """Local and hybrid modes call aquery_context with the expected mode."""
    calls: list[tuple[str, str]] = []

    async def fake_aquery(question: str, *, mode: str) -> str:
        """Record mode selection and return a context blob with a movie key."""
        calls.append((question, mode))
        return f"context for {question} movie:42"

    monkeypatch.setattr("agents.retrieval.aquery_context", fake_aquery)

    from agents import retrieval

    local = await retrieval.query_local_context("Who starred in X?")
    hybrid = await retrieval.query_hybrid_context("a movie about survival")

    assert local == "context for Who starred in X? movie:42"
    assert hybrid == ["context for a movie about survival movie:42"]
    assert calls == [
        ("Who starred in X?", "local"),
        ("a movie about survival", "hybrid"),
    ]


def test_run_graph_query_bridges_async(monkeypatch) -> None:
    """Sync tools keep the nodes.py signature over the async facade."""

    async def fake_local(question: str) -> str:
        """Return a fixed local-mode context."""
        return f"local:{question} movie:7"

    monkeypatch.setattr("agents.retrieval.query_local_context", fake_local)
    assert tools.run_graph_query("cast of Foo") == "local:cast of Foo movie:7"


def test_recommendation_fallback_formats_movie_keys(monkeypatch) -> None:
    """Fallback movies include movie:{id} tokens for artifact recovery."""
    monkeypatch.setattr(
        "agents.retrieval.fetch_top_box_office_movies",
        lambda limit: [
            {
                "id": "movie:1",
                "wikipedia_id": "1",
                "title": "Hit",
                "year": 2010,
                "box_office": 999,
                "poster_url": None,
                "subtitle": None,
            }
        ],
    )
    monkeypatch.setattr(
        "agents.retrieval.fetch_cast_names",
        lambda ids, limit_per_movie=12, include_characters=False: {"movie:1": ["Star"]},
    )
    monkeypatch.setattr(
        "agents.retrieval.get_settings",
        lambda: type("S", (), {"retrieval_top_k": 5})(),
    )

    rows = tools.run_recommendation_fallback(limit=1)
    assert len(rows) == 1
    assert "movie:1" in rows[0]
    assert "Hit" in rows[0]


def test_rerank_preserves_untruncated_context_for_movie_key_recovery(monkeypatch) -> None:
    """Reranking bounds its prompt but returns the original keyed context."""
    candidate = f"{'x' * 3_000} movie:42"
    fake_llm = SimpleNamespace(
        invoke=lambda _prompt: SimpleNamespace(content="[0]"),
    )
    monkeypatch.setattr("agents.tools.get_utility_llm", lambda: fake_llm)
    monkeypatch.setattr(
        "agents.tools.get_settings",
        lambda: SimpleNamespace(rerank_top_k=5),
    )

    assert tools.run_rerank("question", [candidate]) == [candidate]
