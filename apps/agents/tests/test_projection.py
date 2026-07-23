"""Tests for projection query behavior."""

from agents.projection import fetch_movie_neighbourhood, find_movies_mentioned_in_text


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


def test_title_recovery_filters_in_postgres(monkeypatch) -> None:
    """Title fallback sends one bounded, parameterized containment query."""
    calls: list[tuple[str, tuple[object, ...]]] = []
    row = {
        "id": "movie:13",
        "wikipedia_id": "13",
        "title": "Forrest Gump",
        "year": 1994,
        "box_office": 1,
        "poster_url": None,
        "subtitle": None,
    }

    class FakeCursor:
        """Cursor returning one title candidate."""

        def fetchall(self):
            """Return matching projection rows."""
            return [row]

    class FakeConnection:
        """Connection recording the parameterized lookup."""

        def execute(self, query: str, params: tuple[object, ...]):
            """Record SQL and return a cursor."""
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
        """Pool exposing one fake connection."""

        def connection(self):
            """Return the fake context."""
            return ConnectionContext()

    monkeypatch.setattr("agents.projection.get_projection_pool", lambda: FakePool())

    movies = find_movies_mentioned_in_text("A story like Forrest Gump", limit=40)

    assert movies[0]["id"] == "movie:13"
    assert calls[0][1] == ("A story like Forrest Gump", 40)
    assert "strpos(lower(%s), lower(title))" in calls[0][0]
