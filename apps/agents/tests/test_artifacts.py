"""Unit tests for retrieval artifact parsing."""

from types import SimpleNamespace

from agents.artifacts import (
    build_retrieval_artifacts,
    cited_titles_from_answer,
    extract_movie_titles,
    filter_artifacts_by_answer,
    full_graph,
    sources_from_candidates,
)

_SAMPLE_CHUNK = (
    'Movie: Forrest Gump (1994) - tagline: "Life is like a box of chocolates"\n'
    "Cast: Tom Hanks as Forrest Gump; Robin Wright as Jenny Curran\n"
    "Directed by: Robert Zemeckis"
)


def test_extract_movie_titles_from_semantic_chunk() -> None:
    """Semantic neighbourhood text yields a de-duplicated movie title list."""
    titles = extract_movie_titles([_SAMPLE_CHUNK, _SAMPLE_CHUNK])
    assert titles == ["Forrest Gump"]


def test_sources_from_candidates_builds_cards() -> None:
    """Movie neighbourhood chunks become structured source cards."""
    sources = sources_from_candidates([_SAMPLE_CHUNK])
    assert len(sources) == 1
    assert sources[0]["title"] == "Forrest Gump"
    assert sources[0]["year"] == "1994"
    assert "Tom Hanks" in sources[0]["tags"]
    assert "Robert Zemeckis" in sources[0]["tags"]
    assert sources[0]["poster_url"] is None or sources[0]["poster_url"].startswith("https://")


def test_build_retrieval_artifacts_without_neo4j() -> None:
    """Graph lookup fail-open still returns parsed sources when Neo4j is unavailable."""
    artifacts = build_retrieval_artifacts([_SAMPLE_CHUNK])
    assert len(artifacts["sources"]) == 1
    assert artifacts["graph"]["nodes"] == [] or len(artifacts["graph"]["nodes"]) >= 0


def test_full_graph_normalizes_neo4j_rows(monkeypatch) -> None:
    """Full graph rows become stable nodes and labelled links without live Neo4j."""

    class FakeTransaction:
        """Minimal Neo4j transaction stub for full graph queries."""

        def run(self, query: str, **_params):
            """Return deterministic node/link rows for the requested query."""
            if "RETURN labels(n)" in query:
                return [
                    {"labels": ["Movie"], "title": "The Matrix", "name": None},
                    {"labels": ["Person"], "title": None, "name": "Keanu Reeves"},
                ]
            return [
                {
                    "source_labels": ["Person"],
                    "source_title": None,
                    "source_name": "Keanu Reeves",
                    "target_labels": ["Movie"],
                    "target_title": "The Matrix",
                    "target_name": None,
                    "rel_type": "ACTED_IN",
                }
            ]

    class FakeSession:
        """Context manager stub that executes read callbacks."""

        def __enter__(self):
            """Return the fake session."""
            return self

        def __exit__(self, *_exc_info) -> None:
            """Close the fake session."""

        def execute_read(self, callback):
            """Run the callback with a fake transaction."""
            return callback(FakeTransaction())

    class FakeDriver:
        """Neo4j driver stub exposing sessions."""

        def session(self, *, database: str):
            """Return a fake session for the configured database."""
            assert database == "neo4j"
            return FakeSession()

    full_graph.cache_clear()
    monkeypatch.setattr(
        "agents.artifacts.get_settings",
        lambda: SimpleNamespace(neo4j_database="neo4j"),
    )
    monkeypatch.setattr("agents.artifacts.get_neo4j_driver", lambda: FakeDriver())

    graph = full_graph()

    assert graph["nodes"] == [
        {"id": "movie:the-matrix", "label": "The Matrix", "type": "Movie"},
        {"id": "person:keanu-reeves", "label": "Keanu Reeves", "type": "Person"},
    ]
    assert graph["links"] == [
        {
            "source": "person:keanu-reeves",
            "target": "movie:the-matrix",
            "label": "Acted In",
        }
    ]
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
    sources = sources_from_candidates([_SAMPLE_CHUNK])
    extra = sources_from_candidates(
        [
            'Movie: The Matrix (1999) - tagline: "Welcome to the Real World"\n'
            "Directed by: Lana Wachowski"
        ]
    )
    all_sources = sources + extra
    graph = {
        "nodes": [
            {"id": "movie-forrest-gump", "label": "Forrest Gump", "type": "Movie"},
            {"id": "movie-the-matrix", "label": "The Matrix", "type": "Movie"},
            {"id": "person-tom-hanks", "label": "Tom Hanks", "type": "Person"},
        ],
        "links": [
            {
                "source": "person-tom-hanks",
                "target": "movie-forrest-gump",
                "label": "Acted In",
            }
        ],
    }
    filtered = filter_artifacts_by_answer(
        all_sources,
        graph,
        "I recommend watching Forrest Gump tonight.",
    )
    assert len(filtered["sources"]) == 1
    assert filtered["sources"][0]["title"] == "Forrest Gump"
    assert {node["label"] for node in filtered["graph"]["nodes"]} == {
        "Forrest Gump",
        "Tom Hanks",
    }
