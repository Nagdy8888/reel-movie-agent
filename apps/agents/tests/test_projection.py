"""Tests for projection query behavior."""

from agents.projection import fetch_movie_neighbourhood


def test_focused_neighbourhood_uses_one_database_query(monkeypatch) -> None:
    """Sources and focused graph rows hydrate in one pooled SQL query."""
    calls: list[tuple[str, tuple[object, ...]]] = []
    payload = {
        "movies": [
            {
                "id": "movie:1",
                "wikipedia_id": "1",
                "title": "One",
                "year": 2001,
                "box_office": 100,
                "poster_url": None,
                "subtitle": None,
            }
        ],
        "people": [{"id": "person:a", "name": "Actor"}],
        "genres": [{"id": "genre:drama", "name": "Drama"}],
        "acted_in": [
            {
                "person_id": "person:a",
                "movie_id": "movie:1",
                "character": "Lead",
                "billing_order": 0,
            }
        ],
        "in_genre": [{"movie_id": "movie:1", "genre_id": "genre:drama"}],
    }

    class FakeCursor:
        """Cursor returning the aggregate projection payload."""

        def fetchone(self):
            """Return one aggregate row."""
            return payload

    class FakeConnection:
        """Connection recording SQL executions."""

        def execute(self, query: str, params: tuple[object, ...]):
            """Record the single focused hydration query."""
            calls.append((query, params))
            return FakeCursor()

    class ConnectionContext:
        """Context manager yielding a fake connection."""

        def __enter__(self):
            """Return the fake connection."""
            return FakeConnection()

        def __exit__(self, *_args: object) -> None:
            """Close the fake context."""

    class FakePool:
        """Pool exposing one fake connection context."""

        def connection(self):
            """Return the fake connection context."""
            return ConnectionContext()

    monkeypatch.setattr("agents.projection.get_projection_pool", lambda: FakePool())

    movies, people, genres, acted_in, in_genre = fetch_movie_neighbourhood(["movie:1"])

    assert len(calls) == 1
    assert calls[0][1] == (["movie:1"],)
    assert movies[0]["title"] == "One"
    assert people[0]["name"] == "Actor"
    assert genres[0]["name"] == "Drama"
    assert acted_in[0]["billing_order"] == 0
    assert in_genre[0]["genre_id"] == "genre:drama"
