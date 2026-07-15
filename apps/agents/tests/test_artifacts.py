"""Unit tests for retrieval artifact parsing and projection hydration."""

from agents.artifacts import (
    artifacts_from_movie_keys,
    build_retrieval_artifacts,
    cited_titles_from_answer,
    extract_movie_ids,
    extract_movie_keys,
    extract_movie_titles,
    filter_artifacts_by_answer,
    full_graph,
    sources_from_candidates,
)

_SAMPLE_CHUNK = (
    "Movie: Forrest Gump (1994) [movie:13]\n"
    "Poster URL: https://image.tmdb.org/t/p/w500/forrest.jpg\n"
    "Cast: Tom Hanks as Forrest Gump; Robin Wright as Jenny Curran"
)


def test_extract_movie_titles_from_semantic_chunk() -> None:
    """Formatted movie blocks yield a de-duplicated movie title list."""
    titles = extract_movie_titles([_SAMPLE_CHUNK, _SAMPLE_CHUNK])
    assert titles == ["Forrest Gump"]


def test_extract_movie_keys_from_file_path_tokens() -> None:
    """LightRAG file_path tokens recover stable movie keys."""
    keys = extract_movie_keys(["--- file_path: movie:13 ---\nSome entity context", "also movie:99"])
    assert keys == ["movie:13", "movie:99"]


def test_extract_movie_ids_deduplicates_stable_ids() -> None:
    """Movie keys expose unique Wikipedia IDs."""
    ids = extract_movie_ids([_SAMPLE_CHUNK, "context mentioning movie:13 again"])
    assert ids == [13]


def test_extract_movie_keys_title_fallback(monkeypatch) -> None:
    """When keys are absent, titles found in context map to projection IDs."""
    monkeypatch.setattr(
        "agents.artifacts.list_movie_titles",
        lambda: ["Forrest Gump", "The Matrix"],
    )
    monkeypatch.setattr(
        "agents.artifacts.fetch_movies_by_titles",
        lambda titles: (
            [
                {
                    "id": "movie:13",
                    "wikipedia_id": "13",
                    "title": "Forrest Gump",
                    "year": 1994,
                    "box_office": 1,
                    "poster_url": None,
                    "subtitle": None,
                }
            ]
            if "Forrest Gump" in titles
            else []
        ),
    )
    keys = extract_movie_keys(["A long LightRAG answer about Forrest Gump themes"])
    assert keys == ["movie:13"]


def test_sources_from_candidates_builds_cards(monkeypatch) -> None:
    """Movie neighbourhood chunks become structured source cards."""

    def fake_artifacts(keys: list[str]):
        """Return projection-backed cards for recovered keys."""
        assert keys == ["movie:13"]
        return {
            "sources": [
                {
                    "id": "movie:13",
                    "title": "Forrest Gump",
                    "subtitle": None,
                    "year": "1994",
                    "poster_url": "https://image.tmdb.org/t/p/w500/forrest.jpg",
                    "tags": ["Tom Hanks"],
                }
            ],
            "graph": {"nodes": [], "links": []},
        }

    monkeypatch.setattr("agents.artifacts.artifacts_from_movie_keys", fake_artifacts)
    sources = sources_from_candidates([_SAMPLE_CHUNK])
    assert len(sources) == 1
    assert sources[0]["title"] == "Forrest Gump"
    assert sources[0]["id"] == "movie:13"
    assert sources[0]["poster_url"] == "https://image.tmdb.org/t/p/w500/forrest.jpg"


def test_build_retrieval_artifacts_without_projection(monkeypatch) -> None:
    """Projection lookup fail-open still returns empty graph cleanly."""

    def boom(_keys: list[str]):
        """Simulate unreachable Supabase projection."""
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr("agents.artifacts.artifacts_from_movie_keys", boom)
    artifacts = build_retrieval_artifacts([_SAMPLE_CHUNK])
    # sources_from_candidates also calls artifacts_from_movie_keys, then
    # falls back to parsing the Movie: line when that raises.
    assert len(artifacts["sources"]) == 1
    assert artifacts["sources"][0]["title"] == "Forrest Gump"
    assert artifacts["graph"]["nodes"] == []


def test_artifacts_from_movie_keys_hydrates_neighbourhood(monkeypatch) -> None:
    """Projection neighbourhood rows become source cards and graph links."""
    monkeypatch.setattr(
        "agents.artifacts.fetch_movie_neighbourhood",
        lambda _keys: (
            [
                {
                    "id": "movie:13",
                    "wikipedia_id": "13",
                    "title": "Forrest Gump",
                    "year": 1994,
                    "box_office": 1,
                    "poster_url": "https://image.tmdb.org/forrest.jpg",
                    "subtitle": None,
                }
            ],
            [{"id": "person:%2Fm%2F0b1zz", "name": "Tom Hanks"}],
            [{"id": "genre:drama", "name": "Drama"}],
            [
                {
                    "person_id": "person:%2Fm%2F0b1zz",
                    "movie_id": "movie:13",
                    "character": "Forrest",
                    "billing_order": 0,
                }
            ],
            [{"movie_id": "movie:13", "genre_id": "genre:drama"}],
        ),
    )
    artifacts = artifacts_from_movie_keys(["movie:13"])

    assert artifacts["sources"][0]["id"] == "movie:13"
    assert artifacts["sources"][0]["tags"] == ["Tom Hanks"]
    assert {node["id"] for node in artifacts["graph"]["nodes"]} == {
        "movie:13",
        "person:%2Fm%2F0b1zz",
        "genre:drama",
    }
    assert {"Acted In", "In Genre"} == {link["label"] for link in artifacts["graph"]["links"]}


def test_full_graph_cache_and_projection(monkeypatch) -> None:
    """Full graph loads from the projection and never caches an empty result."""
    calls = {"n": 0}

    def fake_projection():
        """Return a tiny projection graph once, then empty (should clear cache)."""
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                [
                    {
                        "id": "movie:603",
                        "wikipedia_id": "603",
                        "title": "The Matrix",
                        "year": 1999,
                        "box_office": 1,
                        "poster_url": None,
                        "subtitle": None,
                    }
                ],
                [{"id": "person:a", "name": "Keanu Reeves"}],
                [{"id": "genre:science%20fiction", "name": "Science Fiction"}],
                [
                    {
                        "person_id": "person:a",
                        "movie_id": "movie:603",
                        "character": "Neo",
                        "billing_order": 0,
                    }
                ],
                [{"movie_id": "movie:603", "genre_id": "genre:science%20fiction"}],
            )
        return [], [], [], [], []

    full_graph.cache_clear()
    monkeypatch.setattr("agents.artifacts.fetch_full_projection", fake_projection)

    graph = full_graph()
    assert {node["label"] for node in graph["nodes"]} == {
        "The Matrix",
        "Keanu Reeves",
        "Science Fiction",
    }
    assert graph["links"][0]["label"] == "Acted In"

    full_graph.cache_clear()
    empty = full_graph()
    assert empty["nodes"] == []
    # Empty snapshot must not stick in the lru_cache.
    monkeypatch.setattr(
        "agents.artifacts.fetch_full_projection",
        lambda: (
            [
                {
                    "id": "movie:1",
                    "wikipedia_id": "1",
                    "title": "One",
                    "year": None,
                    "box_office": None,
                    "poster_url": None,
                    "subtitle": None,
                }
            ],
            [],
            [],
            [],
            [],
        ),
    )
    rebuilt = full_graph()
    assert rebuilt["nodes"][0]["id"] == "movie:1"
    full_graph.cache_clear()


def test_cited_titles_from_answer_preserves_order() -> None:
    """Titles are returned in the order they appear in the assistant answer."""
    titles = cited_titles_from_answer(
        "Try The Matrix first, then Forrest Gump.",
        ["Forrest Gump", "The Matrix"],
    )
    assert titles == ["The Matrix", "Forrest Gump"]


def test_filter_artifacts_by_answer_keeps_only_cited_movies() -> None:
    """The right pane should match movies cited in the grounded answer."""
    sources = [
        {
            "id": "movie:13",
            "title": "Forrest Gump",
            "subtitle": None,
            "year": "1994",
            "poster_url": None,
            "tags": ["Tom Hanks"],
        },
        {
            "id": "movie:603",
            "title": "The Matrix",
            "subtitle": None,
            "year": "1999",
            "poster_url": None,
            "tags": [],
        },
    ]
    graph = {
        "nodes": [
            {"id": "movie:13", "label": "Forrest Gump", "type": "Movie"},
            {"id": "movie:603", "label": "The Matrix", "type": "Movie"},
            {"id": "person:31", "label": "Tom Hanks", "type": "Person"},
        ],
        "links": [
            {
                "source": "person:31",
                "target": "movie:13",
                "label": "Acted In",
            }
        ],
    }
    filtered = filter_artifacts_by_answer(
        sources,
        graph,
        "I recommend watching Forrest Gump tonight.",
    )
    assert len(filtered["sources"]) == 1
    assert filtered["sources"][0]["title"] == "Forrest Gump"
    assert {node["label"] for node in filtered["graph"]["nodes"]} == {
        "Forrest Gump",
        "Tom Hanks",
    }
