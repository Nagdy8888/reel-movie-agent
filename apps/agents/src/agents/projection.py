"""Supabase Movie/Person/Genre projection reads used by the graph UI."""

from __future__ import annotations

from typing import Any, TypedDict
from urllib.parse import quote

import psycopg
from psycopg.rows import dict_row

from agents.settings import get_settings


class MovieRow(TypedDict):
    """A movie row from the UI projection."""

    id: str
    wikipedia_id: str
    title: str
    year: int | None
    box_office: int | None
    poster_url: str | None
    subtitle: str | None


class PersonRow(TypedDict):
    """A person row from the UI projection."""

    id: str
    name: str


class GenreRow(TypedDict):
    """A genre row from the UI projection."""

    id: str
    name: str


class ActedInRow(TypedDict):
    """An acted_in edge from the UI projection."""

    person_id: str
    movie_id: str
    character: str | None
    billing_order: int | None


class InGenreRow(TypedDict):
    """An in_genre edge from the UI projection."""

    movie_id: str
    genre_id: str


def named_node_id(kind: str, name: str) -> str:
    """Return a collision-safe ID for a unique named graph node.

    Args:
        kind: Node kind prefix (e.g. ``genre``).
        name: Display name used to derive the ID.

    Returns:
        An ID of the form ``{kind}:{percent-quoted casefold(name)}``.
    """
    return f"{kind.lower()}:{quote(name.casefold(), safe='')}"


def person_id_from_freebase(freebase_actor_id: str) -> str:
    """Build a stable person ID from a Freebase actor ID.

    Args:
        freebase_actor_id: Freebase ID such as ``/m/0346l4``.

    Returns:
        An ID of the form ``person:{percent-quoted freebase_id}``.
    """
    return f"person:{quote(freebase_actor_id, safe='')}"


def movie_id_from_wikipedia(wikipedia_id: str | int) -> str:
    """Build a stable movie ID from a Wikipedia movie ID.

    Args:
        wikipedia_id: CMU/Wikipedia movie identifier.

    Returns:
        An ID of the form ``movie:{wikipedia_id}``.
    """
    return f"movie:{wikipedia_id}"


def _connect() -> Any:
    """Open a sync Supabase Postgres connection for projection queries."""
    settings = get_settings()
    # psycopg stubs type ``connect`` as TupleRow; dict_row is correct at runtime.
    return psycopg.connect(settings.supabase_db_url, row_factory=dict_row)  # type: ignore[arg-type]


def fetch_movies_by_ids(movie_ids: list[str]) -> list[MovieRow]:
    """Load movies by stable projection IDs, preserving request order.

    Args:
        movie_ids: ``movie:{wikipedia_id}`` keys.

    Returns:
        Matching movie rows in the same order as ``movie_ids``.
    """
    if not movie_ids:
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, wikipedia_id, title, year, box_office, poster_url, subtitle
            FROM public.movies
            WHERE id = ANY(%s)
            """,
            (movie_ids,),
        ).fetchall()
    by_id = {str(row["id"]): MovieRow(**row) for row in rows}
    return [by_id[mid] for mid in movie_ids if mid in by_id]


def fetch_movies_by_titles(titles: list[str]) -> list[MovieRow]:
    """Resolve movie titles (case-insensitive) to projection rows.

    Args:
        titles: Candidate movie titles from retrieval context.

    Returns:
        Matching movies in first-seen title order (duplicates skipped).
    """
    if not titles:
        return []
    lowered = [title.casefold() for title in titles]
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, wikipedia_id, title, year, box_office, poster_url, subtitle
            FROM public.movies
            WHERE lower(title) = ANY(%s)
            """,
            (lowered,),
        ).fetchall()
    by_title = {str(row["title"]).casefold(): MovieRow(**row) for row in rows}
    seen: set[str] = set()
    result: list[MovieRow] = []
    for title in titles:
        key = title.casefold()
        movie = by_title.get(key)
        if movie is None or movie["id"] in seen:
            continue
        seen.add(movie["id"])
        result.append(movie)
    return result


def fetch_cast_names(movie_ids: list[str], *, limit_per_movie: int = 2) -> dict[str, list[str]]:
    """Return top-billed actor names for each movie.

    Args:
        movie_ids: Movie projection IDs.
        limit_per_movie: Maximum actor names per movie.

    Returns:
        Mapping of movie_id → actor name list.
    """
    if not movie_ids:
        return {}
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT ai.movie_id, p.name, ai.billing_order
            FROM public.acted_in ai
            JOIN public.people p ON p.id = ai.person_id
            WHERE ai.movie_id = ANY(%s)
            ORDER BY ai.movie_id, ai.billing_order NULLS LAST, p.name
            """,
            (movie_ids,),
        ).fetchall()
    result: dict[str, list[str]] = {mid: [] for mid in movie_ids}
    for row in rows:
        movie_id = str(row["movie_id"])
        names = result.setdefault(movie_id, [])
        if len(names) >= limit_per_movie:
            continue
        name = str(row["name"]).strip()
        if name and name not in names:
            names.append(name)
    return result


def fetch_movie_neighbourhood(
    movie_ids: list[str],
) -> tuple[
    list[MovieRow],
    list[PersonRow],
    list[GenreRow],
    list[ActedInRow],
    list[InGenreRow],
]:
    """Load cited movies plus connected people/genres and edges.

    Args:
        movie_ids: Movie projection IDs to expand.

    Returns:
        Movies, people, genres, acted_in edges, and in_genre edges.
    """
    movies = fetch_movies_by_ids(movie_ids)
    if not movies:
        return [], [], [], [], []
    ids = [m["id"] for m in movies]
    with _connect() as conn:
        people = [
            PersonRow(**row)
            for row in conn.execute(
                """
                SELECT DISTINCT p.id, p.name
                FROM public.people p
                JOIN public.acted_in ai ON ai.person_id = p.id
                WHERE ai.movie_id = ANY(%s)
                """,
                (ids,),
            ).fetchall()
        ]
        genres = [
            GenreRow(**row)
            for row in conn.execute(
                """
                SELECT DISTINCT g.id, g.name
                FROM public.genres g
                JOIN public.in_genre ig ON ig.genre_id = g.id
                WHERE ig.movie_id = ANY(%s)
                """,
                (ids,),
            ).fetchall()
        ]
        acted_in = [
            ActedInRow(**row)
            for row in conn.execute(
                """
                SELECT person_id, movie_id, character, billing_order
                FROM public.acted_in
                WHERE movie_id = ANY(%s)
                """,
                (ids,),
            ).fetchall()
        ]
        in_genre = [
            InGenreRow(**row)
            for row in conn.execute(
                """
                SELECT movie_id, genre_id
                FROM public.in_genre
                WHERE movie_id = ANY(%s)
                """,
                (ids,),
            ).fetchall()
        ]
    return movies, people, genres, acted_in, in_genre


def fetch_full_projection() -> tuple[
    list[MovieRow],
    list[PersonRow],
    list[GenreRow],
    list[ActedInRow],
    list[InGenreRow],
]:
    """Load the entire Movie/Person/Genre projection for ``/graph``.

    Returns:
        All projection nodes and edges for the ingested subset.
    """
    with _connect() as conn:
        movies = [
            MovieRow(**row)
            for row in conn.execute(
                """
                SELECT id, wikipedia_id, title, year, box_office, poster_url, subtitle
                FROM public.movies
                ORDER BY box_office DESC NULLS LAST, id
                """
            ).fetchall()
        ]
        people = [
            PersonRow(**row)
            for row in conn.execute("SELECT id, name FROM public.people ORDER BY name").fetchall()
        ]
        genres = [
            GenreRow(**row)
            for row in conn.execute("SELECT id, name FROM public.genres ORDER BY name").fetchall()
        ]
        acted_in = [
            ActedInRow(**row)
            for row in conn.execute(
                """
                SELECT person_id, movie_id, character, billing_order
                FROM public.acted_in
                """
            ).fetchall()
        ]
        in_genre = [
            InGenreRow(**row)
            for row in conn.execute("SELECT movie_id, genre_id FROM public.in_genre").fetchall()
        ]
    return movies, people, genres, acted_in, in_genre


def fetch_top_box_office_movies(limit: int) -> list[MovieRow]:
    """Return top movies by box office for recommendation fallback.

    Args:
        limit: Maximum number of movies.

    Returns:
        Movies ordered by box office descending.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, wikipedia_id, title, year, box_office, poster_url, subtitle
            FROM public.movies
            ORDER BY box_office DESC NULLS LAST, id
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [MovieRow(**row) for row in rows]


def list_movie_titles() -> list[str]:
    """Return all projection movie titles for title-fallback recovery.

    Returns:
        Title strings currently stored in ``public.movies``.
    """
    with _connect() as conn:
        rows = conn.execute("SELECT title FROM public.movies ORDER BY title").fetchall()
    return [str(row["title"]) for row in rows if row.get("title")]


def format_movie_context(
    movie: MovieRow,
    *,
    cast: list[str] | None = None,
    genres: list[str] | None = None,
) -> str:
    """Format a projection movie into a grounding string with movie keys.

    Args:
        movie: Projection movie row.
        cast: Optional actor names.
        genres: Optional genre names.

    Returns:
        A multi-line context block that includes ``movie:{wikipedia_id}``.
    """
    year = f" ({movie['year']})" if movie.get("year") is not None else ""
    lines = [
        f"Movie: {movie['title']}{year} [{movie['id']}]",
    ]
    if movie.get("box_office") is not None:
        lines.append(f"Box office: {movie['box_office']}")
    if movie.get("poster_url"):
        lines.append(f"Poster URL: {movie['poster_url']}")
    if genres:
        lines.append(f"Genres: {', '.join(genres)}")
    if cast:
        lines.append(f"Cast: {'; '.join(cast)}")
    return "\n".join(lines)
