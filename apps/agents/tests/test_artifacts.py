"""Unit tests for retrieval artifact parsing."""

from types import SimpleNamespace

from agents.artifacts import (
    _node_artifact,
    artifacts_from_movie_ids,
    build_retrieval_artifacts,
    cited_titles_from_answer,
    extract_movie_ids,
    extract_movie_titles,
    filter_artifacts_by_answer,
    full_graph,
    sources_from_candidates,
)

_SAMPLE_CHUNK = (
    "Movie: Forrest Gump (1994) [TMDB ID: 13]\n"
    "Tagline: Life is like a box of chocolates\n"
    "Poster URL: https://image.tmdb.org/t/p/w500/forrest.jpg\n"
    "Cast: Tom Hanks as Forrest Gump; Robin Wright as Jenny Curran\n"
    "Directed by: Robert Zemeckis"
)


def test_extract_movie_titles_from_semantic_chunk() -> None:
    """Semantic neighbourhood text yields a de-duplicated movie title list."""
    titles = extract_movie_titles([_SAMPLE_CHUNK, _SAMPLE_CHUNK])
    assert titles == ["Forrest Gump"]


def test_extract_movie_ids_deduplicates_stable_ids() -> None:
    """Semantic and structured candidates should expose stable TMDB IDs."""
    ids = extract_movie_ids([_SAMPLE_CHUNK, "{'tmdbId': 13, 'title': 'Forrest Gump'}"])
    assert ids == [13]


def test_tmdb_ids_prevent_duplicate_title_and_person_name_collisions() -> None:
    """Display-name duplicates should remain distinct graph nodes."""
    movie_a = _node_artifact(["Movie"], 1, "The Return", None)
    movie_b = _node_artifact(["Movie"], 2, "The Return", None)
    person_a = _node_artifact(["Person"], 10, None, "Alex Smith")
    person_b = _node_artifact(["Person"], 20, None, "Alex Smith")

    assert movie_a is not None and movie_b is not None
    assert person_a is not None and person_b is not None
    assert movie_a["id"] != movie_b["id"]
    assert person_a["id"] != person_b["id"]


def test_sources_from_candidates_builds_cards() -> None:
    """Movie neighbourhood chunks become structured source cards."""
    sources = sources_from_candidates([_SAMPLE_CHUNK])
    assert len(sources) == 1
    assert sources[0]["title"] == "Forrest Gump"
    assert sources[0]["year"] == "1994"
    assert "Tom Hanks" in sources[0]["tags"]
    assert "Robert Zemeckis" in sources[0]["tags"]
    assert sources[0]["id"] == "movie:13"
    assert sources[0]["poster_url"] == "https://image.tmdb.org/t/p/w500/forrest.jpg"


def test_build_retrieval_artifacts_without_neo4j(monkeypatch) -> None:
    """Graph lookup fail-open still returns parsed sources when Neo4j is unavailable."""

    def unavailable_settings():
        """Simulate missing agent settings / unreachable Neo4j config."""
        raise RuntimeError("neo4j unavailable")

    monkeypatch.setattr("agents.artifacts.get_settings", unavailable_settings)
    artifacts = build_retrieval_artifacts([_SAMPLE_CHUNK])
    assert len(artifacts["sources"]) == 1
    assert artifacts["sources"][0]["title"] == "Forrest Gump"
    assert artifacts["graph"]["nodes"] == []
    assert artifacts["graph"]["links"] == []


def test_structured_graph_facts_hydrate_sources_and_highlights(monkeypatch) -> None:
    """Text2Cypher rows should create source cards and graph highlights."""
    captured_ids: list[list[int]] = []

    def fake_artifacts(movie_ids: list[int]):
        """Return canonical sources and graph data for captured IDs."""
        captured_ids.append(movie_ids)
        return {
            "sources": [
                {
                    "id": "movie:13",
                    "title": "Forrest Gump",
                    "subtitle": "Life is like a box of chocolates",
                    "year": "1994",
                    "poster_url": "https://image.tmdb.org/t/p/w500/forrest.jpg",
                    "tags": ["Robert Zemeckis", "Tom Hanks"],
                }
            ],
            "graph": {
                "nodes": [{"id": "movie:13", "label": "Forrest Gump", "type": "Movie"}],
                "links": [],
            },
        }

    monkeypatch.setattr("agents.artifacts.artifacts_from_movie_ids", fake_artifacts)

    artifacts = build_retrieval_artifacts(
        ["[Graph facts]\n{'m.tmdbId': 13, 'm.title': 'Forrest Gump', 'm.year': 1994}"]
    )

    assert captured_ids == [[13]]
    assert artifacts["sources"][0]["id"] == "movie:13"
    assert artifacts["graph"]["nodes"][0]["id"] == "movie:13"


def test_title_only_graph_facts_resolve_stable_ids(monkeypatch) -> None:
    """Title-only Text2Cypher output should be resolved before artifacts load."""

    def fake_artifacts(movie_ids: list[int]):
        """Return combined artifacts for the resolved movie ID."""
        return {
            "sources": [
                {
                    "id": f"movie:{movie_ids[0]}",
                    "title": "Forrest Gump",
                    "subtitle": None,
                    "year": "1994",
                    "poster_url": None,
                    "tags": [],
                }
            ],
            "graph": {
                "nodes": [
                    {
                        "id": f"movie:{movie_ids[0]}",
                        "label": "Forrest Gump",
                        "type": "Movie",
                    }
                ],
                "links": [],
            },
        }

    monkeypatch.setattr("agents.artifacts._resolve_movie_ids", lambda titles: [13])
    monkeypatch.setattr("agents.artifacts.artifacts_from_movie_ids", fake_artifacts)

    artifacts = build_retrieval_artifacts(
        ["[Graph facts]\n{'m.title': 'Forrest Gump', 'm.year': 1994}"]
    )

    assert artifacts["sources"][0]["id"] == "movie:13"
    assert artifacts["graph"]["nodes"][0]["id"] == "movie:13"


def test_artifacts_from_movie_ids_uses_one_read_query(monkeypatch) -> None:
    """One read query should hydrate both source cards and graph neighbors."""
    query_calls: list[list[int]] = []

    class FakeTransaction:
        """Transaction stub returning one movie-neighbor row."""

        def run(self, query: str, **params):
            """Capture the bounded IDs and return combined artifact fields."""
            assert "neighbor_labels" in query
            query_calls.append(params["movie_ids"])
            return [
                {
                    "tmdb_id": 13,
                    "title": "Forrest Gump",
                    "year": 1994,
                    "tagline": "Life is like a box of chocolates",
                    "poster_url": "https://image.tmdb.org/forrest.jpg",
                    "directors": ["Robert Zemeckis"],
                    "cast": ["Tom Hanks"],
                    "neighbor_labels": ["Person"],
                    "neighbor_tmdb_id": 31,
                    "neighbor_title": None,
                    "neighbor_name": "Tom Hanks",
                    "rel_type": "ACTED_IN",
                    "movie_is_source": False,
                }
            ]

    class FakeSession:
        """Context manager stub for a read-only Neo4j session."""

        def __enter__(self):
            """Return this fake session."""
            return self

        def __exit__(self, *_exc_info) -> None:
            """Close the fake session."""

        def execute_read(self, callback):
            """Execute the callback once."""
            return callback(FakeTransaction())

    class FakeDriver:
        """Driver stub exposing the fake session."""

        def session(self, *, database: str):
            """Return a fake session for the configured database."""
            assert database == "neo4j"
            return FakeSession()

    monkeypatch.setattr(
        "agents.artifacts.get_settings",
        lambda: SimpleNamespace(neo4j_database="neo4j"),
    )
    monkeypatch.setattr("agents.artifacts.get_neo4j_driver", lambda: FakeDriver())

    artifacts = artifacts_from_movie_ids([13])

    assert query_calls == [[13]]
    assert artifacts["sources"] == [
        {
            "id": "movie:13",
            "title": "Forrest Gump",
            "subtitle": "Life is like a box of chocolates",
            "year": "1994",
            "poster_url": "https://image.tmdb.org/forrest.jpg",
            "tags": ["Robert Zemeckis", "Tom Hanks"],
        }
    ]
    assert {node["id"] for node in artifacts["graph"]["nodes"]} == {
        "movie:13",
        "person:31",
    }
    assert artifacts["graph"]["links"] == [
        {
            "source": "person:31",
            "target": "movie:13",
            "label": "Acted In",
        }
    ]


def test_full_graph_normalizes_neo4j_rows(monkeypatch) -> None:
    """Full graph rows become stable nodes and labelled links without live Neo4j."""

    class FakeTransaction:
        """Minimal Neo4j transaction stub for full graph queries."""

        def run(self, query: str, **_params):
            """Return deterministic node/link rows for the requested query."""
            if "RETURN labels(n)" in query:
                return [
                    {
                        "labels": ["Movie"],
                        "tmdb_id": 603,
                        "title": "The Matrix",
                        "name": None,
                    },
                    {
                        "labels": ["Person"],
                        "tmdb_id": 6384,
                        "title": None,
                        "name": "Keanu Reeves",
                    },
                    {
                        "labels": ["Genre"],
                        "tmdb_id": None,
                        "title": None,
                        "name": "Science Fiction",
                    },
                ]
            return [
                {
                    "source_labels": ["Person"],
                    "source_tmdb_id": 6384,
                    "source_title": None,
                    "source_name": "Keanu Reeves",
                    "target_labels": ["Movie"],
                    "target_tmdb_id": 603,
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
        {"id": "movie:603", "label": "The Matrix", "type": "Movie"},
        {"id": "person:6384", "label": "Keanu Reeves", "type": "Person"},
        {"id": "genre:science%20fiction", "label": "Science Fiction", "type": "Genre"},
    ]
    assert graph["links"] == [
        {
            "source": "person:6384",
            "target": "movie:603",
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


def test_cited_titles_from_answer_ignores_punctuation() -> None:
    """Title matching tolerates answer punctuation differences."""
    titles = cited_titles_from_answer(
        "Tom Hanks acted in That Thing You Do as Mr. White.",
        ["That Thing You Do!"],
    )
    assert titles == ["That Thing You Do!"]


def test_filter_artifacts_by_answer_keeps_only_cited_movies() -> None:
    """The right pane should match movies cited in the grounded answer."""
    sources = sources_from_candidates([_SAMPLE_CHUNK])
    extra = sources_from_candidates(
        [
            "Movie: The Matrix (1999) [TMDB ID: 603]\n"
            "Tagline: Welcome to the Real World\n"
            "Directed by: Lana Wachowski"
        ]
    )
    all_sources = sources + extra
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


def test_filter_artifacts_by_answer_uses_graph_movie_titles_for_highlights() -> None:
    """Graph highlights include answered movies even when source cards are sparse."""
    sources = sources_from_candidates(
        [
            "Movie: Cast Away (2000) [TMDB ID: 8358]\n"
            "Tagline: At the edge of the world\n"
            "Cast: Tom Hanks as Chuck Noland"
        ]
    )
    graph = {
        "nodes": [
            {"id": "movie:9591", "label": "That Thing You Do!", "type": "Movie"},
            {
                "id": "movie:858",
                "label": "Sleepless in Seattle",
                "type": "Movie",
            },
            {"id": "movie:8358", "label": "Cast Away", "type": "Movie"},
            {"id": "movie:9489", "label": "You've Got Mail", "type": "Movie"},
            {"id": "person:31", "label": "Tom Hanks", "type": "Person"},
        ],
        "links": [
            {
                "source": "person:31",
                "target": "movie:9591",
                "label": "Acted In",
            },
            {
                "source": "person:31",
                "target": "movie:858",
                "label": "Acted In",
            },
            {
                "source": "person:31",
                "target": "movie:8358",
                "label": "Acted In",
            },
            {
                "source": "person:31",
                "target": "movie:9489",
                "label": "Acted In",
            },
        ],
    }

    filtered = filter_artifacts_by_answer(
        sources,
        graph,
        (
            "Tom Hanks acted in That Thing You Do as Mr. White, "
            "Sleepless in Seattle as Sam Baldwin, Cast Away as Chuck Noland, "
            "and You've Got Mail as Joe Fox."
        ),
    )

    assert {node["label"] for node in filtered["graph"]["nodes"]} == {
        "That Thing You Do!",
        "Sleepless in Seattle",
        "Cast Away",
        "You've Got Mail",
        "Tom Hanks",
    }
    assert {link["target"] for link in filtered["graph"]["links"]} == {
        "movie:9591",
        "movie:858",
        "movie:8358",
        "movie:9489",
    }
