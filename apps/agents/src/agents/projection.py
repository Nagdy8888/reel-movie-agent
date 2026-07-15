"""Supabase Movie/Person/Genre projection reads used by the graph UI."""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict
from urllib.parse import quote

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

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


@lru_cache(maxsize=1)
def get_projection_pool() -> ConnectionPool[Connection[DictRow]]:
    """Return the shared Supabase projection connection pool."""
    settings = get_settings()
    return ConnectionPool(
        conninfo=settings.supabase_db_url,
        min_size=1,
        max_size=5,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        open=True,
    )


def close_projection_pool() -> None:
    """Close the cached projection pool during process shutdown."""
    if get_projection_pool.cache_info().currsize:
        get_projection_pool().close()
        get_projection_pool.cache_clear()


def fetch_movies_by_ids(movie_ids: list[str]) -> list[MovieRow]:
    """Load movies by stable projection IDs, preserving request order.

    Args:
        movie_ids: ``movie:{wikipedia_id}`` keys.

    Returns:
        Matching movie rows in the same order as ``movie_ids``.
    """
    if not movie_ids:
        return []
    with get_projection_pool().connection() as conn:
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
    with get_projection_pool().connection() as conn:
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
    with get_projection_pool().connection() as conn:
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
    if not movie_ids:
        return [], [], [], [], []
    with get_projection_pool().connection() as conn:
        row = conn.execute(
            """
            WITH requested AS (
                SELECT id, position
                FROM unnest(%s::text[]) WITH ORDINALITY AS request(id, position)
            ),
            selected_movies AS (
                SELECT m.id, m.wikipedia_id, m.title, m.year, m.box_office,
                       m.poster_url, m.subtitle, requested.position
                FROM requested
                JOIN public.movies m ON m.id = requested.id
            ),
            selected_acted AS (
                SELECT ai.person_id, ai.movie_id, ai.character, ai.billing_order
                FROM public.acted_in ai
                JOIN selected_movies m ON m.id = ai.movie_id
            ),
            selected_genres AS (
                SELECT ig.movie_id, ig.genre_id
                FROM public.in_genre ig
                JOIN selected_movies m ON m.id = ig.movie_id
            )
            SELECT
                COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'id', m.id,
                            'wikipedia_id', m.wikipedia_id,
                            'title', m.title,
                            'year', m.year,
                            'box_office', m.box_office,
                            'poster_url', m.poster_url,
                            'subtitle', m.subtitle
                        )
                        ORDER BY m.position
                    )
                    FROM selected_movies m
                ), '[]'::jsonb) AS movies,
                COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object('id', people.id, 'name', people.name)
                        ORDER BY people.name, people.id
                    )
                    FROM (
                        SELECT DISTINCT p.id, p.name
                        FROM public.people p
                        JOIN selected_acted ai ON ai.person_id = p.id
                    ) AS people
                ), '[]'::jsonb) AS people,
                COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object('id', genres.id, 'name', genres.name)
                        ORDER BY genres.name, genres.id
                    )
                    FROM (
                        SELECT DISTINCT g.id, g.name
                        FROM public.genres g
                        JOIN selected_genres ig ON ig.genre_id = g.id
                    ) AS genres
                ), '[]'::jsonb) AS genres,
                COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'person_id', ai.person_id,
                            'movie_id', ai.movie_id,
                            'character', ai.character,
                            'billing_order', ai.billing_order
                        )
                        ORDER BY ai.movie_id, ai.billing_order NULLS LAST, ai.person_id
                    )
                    FROM selected_acted ai
                ), '[]'::jsonb) AS acted_in,
                COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'movie_id', ig.movie_id,
                            'genre_id', ig.genre_id
                        )
                        ORDER BY ig.movie_id, ig.genre_id
                    )
                    FROM selected_genres ig
                ), '[]'::jsonb) AS in_genre
            """,
            (movie_ids,),
        ).fetchone()
    if row is None:
        return [], [], [], [], []
    return (
        [MovieRow(**item) for item in row["movies"]],
        [PersonRow(**item) for item in row["people"]],
        [GenreRow(**item) for item in row["genres"]],
        [ActedInRow(**item) for item in row["acted_in"]],
        [InGenreRow(**item) for item in row["in_genre"]],
    )


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
    with get_projection_pool().connection() as conn:
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
    with get_projection_pool().connection() as conn:
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
    with get_projection_pool().connection() as conn:
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
