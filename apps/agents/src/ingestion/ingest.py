"""Hybrid CMU MovieSummaries ingestion into LightRAG + Supabase projection."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from langsmith import traceable
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from agents.lightrag_service import get_lightrag
from agents.projection import movie_id_from_wikipedia, named_node_id, person_id_from_freebase
from agents.settings import get_settings

_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DATA_DIR = _ROOT / "datasets" / "MovieSummaries"
_TMDB_SEARCH = "https://api.themoviedb.org/3/search/movie"
_TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w500"


@dataclass
class CastMember:
    """One actor credit for a movie."""

    actor_name: str
    person_id: str
    character: str | None
    billing_order: int


@dataclass
class MovieRecord:
    """Joined CMU movie ready for hybrid load."""

    wikipedia_id: str
    title: str
    year: int | None
    box_office: int | None
    genres: list[str]
    summary: str
    cast: list[CastMember] = field(default_factory=list)
    poster_url: str | None = None

    @property
    def movie_id(self) -> str:
        """Return the stable projection / LightRAG document key."""
        return movie_id_from_wikipedia(self.wikipedia_id)


def _parse_year(release_date: str) -> int | None:
    """Extract a 4-digit year from a CMU release_date field."""
    text = release_date.strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _parse_box_office(raw: str) -> int | None:
    """Parse box-office revenue; empty cells become None."""
    text = raw.strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_genre_values(raw: str) -> list[str]:
    """Return genre name values from the CMU JSON genre column."""
    text = raw.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    return [str(value).strip() for value in payload.values() if str(value).strip()]


def load_plot_summaries(path: Path) -> dict[str, str]:
    """Load ``wikipedia_id → summary`` from plot_summaries.txt.

    Args:
        path: Path to the tab-separated plot summaries file.

    Returns:
        Mapping of Wikipedia movie ID to free-text summary.
    """
    summaries: dict[str, str] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t", 1)
            if len(parts) != 2:
                continue
            wiki_id, summary = parts[0].strip(), parts[1].strip()
            if wiki_id and summary:
                summaries[wiki_id] = summary
    return summaries


def load_movie_metadata(path: Path) -> dict[str, dict[str, Any]]:
    """Load movie.metadata.tsv keyed by wikipedia_id.

    Args:
        path: Path to ``movie.metadata.tsv``.

    Returns:
        Mapping of wikipedia_id → parsed metadata fields.
    """
    movies: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 9:
                continue
            wiki_id = cols[0].strip()
            title = cols[2].strip()
            if not wiki_id or not title:
                continue
            movies[wiki_id] = {
                "title": title,
                "year": _parse_year(cols[3]),
                "box_office": _parse_box_office(cols[4]),
                "genres": _parse_genre_values(cols[8]),
            }
    return movies


def load_character_metadata(path: Path) -> dict[str, list[CastMember]]:
    """Load cast lists from character.metadata.tsv keyed by wikipedia_id.

    Args:
        path: Path to ``character.metadata.tsv``.

    Returns:
        Mapping of wikipedia_id → ordered cast members (billing = file order).
    """
    cast_by_movie: dict[str, list[CastMember]] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 13:
                continue
            wiki_id = cols[0].strip()
            actor_name = cols[8].strip()
            freebase_actor_id = cols[12].strip()
            if not wiki_id or not actor_name or not freebase_actor_id:
                continue
            character = cols[3].strip() or None
            members = cast_by_movie.setdefault(wiki_id, [])
            members.append(
                CastMember(
                    actor_name=actor_name,
                    person_id=person_id_from_freebase(freebase_actor_id),
                    character=character,
                    billing_order=len(members),
                )
            )
    return cast_by_movie


def select_subset(
    summaries: dict[str, str],
    metadata: dict[str, dict[str, Any]],
    cast_by_movie: dict[str, list[CastMember]],
    *,
    limit: int,
) -> list[MovieRecord]:
    """Join CMU tables and select the deterministic top-`limit` movies.

    Selection requires a summary, joinable metadata, ≥1 cast row, and a
    non-null box office. Ties break by wikipedia_id ascending.

    Args:
        summaries: Plot summaries by wikipedia_id.
        metadata: Movie metadata by wikipedia_id.
        cast_by_movie: Cast lists by wikipedia_id.
        limit: Maximum movies to keep (``subset_size``).

    Returns:
        Sorted MovieRecord list of length ≤ ``limit``.
    """
    records: list[MovieRecord] = []
    for wiki_id, summary in summaries.items():
        meta = metadata.get(wiki_id)
        cast = cast_by_movie.get(wiki_id)
        if meta is None or not cast:
            continue
        box_office = meta.get("box_office")
        if box_office is None:
            continue
        records.append(
            MovieRecord(
                wikipedia_id=wiki_id,
                title=str(meta["title"]),
                year=meta.get("year"),
                box_office=int(box_office),
                genres=list(meta.get("genres") or []),
                summary=summary,
                cast=cast,
            )
        )
    records.sort(key=lambda m: (-(m.box_office or 0), m.wikipedia_id))
    return records[:limit]


class _RetryableHTTPError(Exception):
    """Raised for transient TMDB HTTP failures that should be retried."""


@retry(
    retry=retry_if_exception_type((_RetryableHTTPError, httpx.TransportError)),
    wait=wait_exponential_jitter(initial=1, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
async def _fetch_poster_url(
    client: httpx.AsyncClient,
    *,
    title: str,
    year: int | None,
    token: str,
) -> str | None:
    """Resolve a TMDB poster URL for a title/year, or None if no hit.

    Args:
        client: Shared async HTTP client.
        title: Movie title.
        year: Optional release year filter.
        token: TMDB v4 bearer token.

    Returns:
        Absolute ``w500`` poster URL, or ``None``.
    """
    params: dict[str, str] = {"query": title}
    if year is not None:
        params["year"] = str(year)
    response = await client.get(
        _TMDB_SEARCH,
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "2")
        await asyncio.sleep(float(retry_after))
        raise _RetryableHTTPError("TMDB rate limited")
    if response.status_code >= 500:
        raise _RetryableHTTPError(f"TMDB server error {response.status_code}")
    if response.status_code != 200:
        return None
    results = response.json().get("results") or []
    if not results:
        return None
    poster_path = results[0].get("poster_path")
    if not poster_path:
        return None
    return f"{_TMDB_POSTER_BASE}{poster_path}"


@traceable(name="enrich_posters")
async def enrich_posters(movies: list[MovieRecord], *, concurrency: int) -> None:
    """Attach TMDB poster URLs onto movie records in place.

    Args:
        movies: Subset movies to enrich.
        concurrency: Semaphore limit for parallel TMDB calls.
    """
    settings = get_settings()
    token = settings.tmdb_api_access_token.strip()
    if not token:
        print("TMDB_API_ACCESS_TOKEN unset; skipping poster enrichment", file=sys.stderr)
        return
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=30.0) as client:

        async def _one(movie: MovieRecord) -> None:
            """Fetch and assign a poster for a single movie."""
            async with semaphore:
                try:
                    movie.poster_url = await _fetch_poster_url(
                        client, title=movie.title, year=movie.year, token=token
                    )
                except Exception as exc:
                    print(
                        f"poster failed for {movie.title}: {exc}",
                        file=sys.stderr,
                    )

        await asyncio.gather(*[_one(movie) for movie in movies])


@traceable(name="upsert_projection")
async def upsert_projection(movies: list[MovieRecord]) -> None:
    """Idempotently write the UI projection tables in Supabase.

    Args:
        movies: Selected subset with optional posters.
    """
    settings = get_settings()
    conn = await asyncpg.connect(dsn=settings.supabase_db_url)
    try:
        async with conn.transaction():
            for movie in movies:
                await conn.execute(
                    """
                    INSERT INTO public.movies (
                        id, wikipedia_id, title, year, box_office, poster_url, subtitle
                    ) VALUES ($1, $2, $3, $4, $5, $6, NULL)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        year = EXCLUDED.year,
                        box_office = EXCLUDED.box_office,
                        poster_url = COALESCE(EXCLUDED.poster_url, public.movies.poster_url),
                        subtitle = EXCLUDED.subtitle
                    """,
                    movie.movie_id,
                    movie.wikipedia_id,
                    movie.title,
                    movie.year,
                    movie.box_office,
                    movie.poster_url,
                )
                for genre_name in movie.genres:
                    genre_id = named_node_id("genre", genre_name)
                    await conn.execute(
                        """
                        INSERT INTO public.genres (id, name)
                        VALUES ($1, $2)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                        """,
                        genre_id,
                        genre_name,
                    )
                    await conn.execute(
                        """
                        INSERT INTO public.in_genre (movie_id, genre_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                        """,
                        movie.movie_id,
                        genre_id,
                    )
                for member in movie.cast:
                    await conn.execute(
                        """
                        INSERT INTO public.people (id, name)
                        VALUES ($1, $2)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                        """,
                        member.person_id,
                        member.actor_name,
                    )
                    await conn.execute(
                        """
                        INSERT INTO public.acted_in (
                            person_id, movie_id, character, billing_order
                        ) VALUES ($1, $2, $3, $4)
                        ON CONFLICT (person_id, movie_id) DO UPDATE SET
                            character = EXCLUDED.character,
                            billing_order = EXCLUDED.billing_order
                        """,
                        member.person_id,
                        movie.movie_id,
                        member.character,
                        member.billing_order,
                    )
    finally:
        await conn.close()


async def _is_processed(rag: Any, doc_id: str) -> bool:
    """Return True if LightRAG already marked ``doc_id`` as processed."""
    try:
        status_store = rag.doc_status
        if hasattr(status_store, "get_by_ids"):
            rows = await status_store.get_by_ids([doc_id])
            if not rows:
                return False
            entry = rows[0] if isinstance(rows, list) else rows.get(doc_id)
            if entry is None:
                return False
            status = (
                entry.get("status") if isinstance(entry, dict) else getattr(entry, "status", None)
            )
            return str(status).lower() in {"processed", "docstatus.processed"}
        if hasattr(status_store, "get_doc_by_id"):
            entry = await status_store.get_doc_by_id(doc_id)
            if entry is None:
                return False
            status = (
                entry.get("status") if isinstance(entry, dict) else getattr(entry, "status", None)
            )
            return str(status).lower() in {"processed", "docstatus.processed"}
    except Exception:
        return False
    return False


@traceable(name="lightrag_insert_subset")
async def insert_into_lightrag(movies: list[MovieRecord], *, concurrency: int) -> int:
    """Insert one LightRAG document per movie (skips already-processed docs).

    Args:
        movies: Selected subset.
        concurrency: Semaphore limit for parallel ``ainsert`` calls.

    Returns:
        Count of newly inserted documents.
    """
    rag = await get_lightrag()
    semaphore = asyncio.Semaphore(concurrency)
    inserted = 0
    lock = asyncio.Lock()

    async def _one(movie: MovieRecord) -> None:
        """Insert a single movie document when not already processed."""
        nonlocal inserted
        doc_id = movie.movie_id
        if await _is_processed(rag, doc_id):
            return
        year_part = f" ({movie.year})" if movie.year is not None else ""
        text = f"{movie.title}{year_part}\n\n{movie.summary}"
        async with semaphore:
            await rag.ainsert(
                [text],
                ids=[doc_id],
                file_paths=[doc_id],
            )
        async with lock:
            inserted += 1
            if inserted % 10 == 0:
                print(f"LightRAG inserted {inserted} new docs...", flush=True)

    await asyncio.gather(*[_one(movie) for movie in movies])
    return inserted


@traceable(name="validate_load")
async def validate_load(movies: list[MovieRecord]) -> None:
    """Assert projection integrity and LightRAG processed-doc count.

    Args:
        movies: The selected subset that should be fully loaded.

    Raises:
        AssertionError: When counts or foreign keys are inconsistent.
    """
    settings = get_settings()
    expected_ids = {m.movie_id for m in movies}
    conn = await asyncpg.connect(dsn=settings.supabase_db_url)
    try:
        movie_count = await conn.fetchval("SELECT count(*) FROM public.movies")
        missing_acted = await conn.fetchval(
            """
            SELECT count(*) FROM public.acted_in ai
            LEFT JOIN public.movies m ON m.id = ai.movie_id
            WHERE m.id IS NULL
            """
        )
        missing_genre = await conn.fetchval(
            """
            SELECT count(*) FROM public.in_genre ig
            LEFT JOIN public.movies m ON m.id = ig.movie_id
            WHERE m.id IS NULL
            """
        )
        loaded_ids = {row["id"] for row in await conn.fetch("SELECT id FROM public.movies")}
    finally:
        await conn.close()

    assert movie_count == len(movies), f"movies={movie_count} expected={len(movies)}"
    assert missing_acted == 0, f"acted_in orphans={missing_acted}"
    assert missing_genre == 0, f"in_genre orphans={missing_genre}"
    assert expected_ids <= loaded_ids, "projection missing selected movie IDs"

    rag = await get_lightrag()
    processed = 0
    for movie in movies:
        if await _is_processed(rag, movie.movie_id):
            processed += 1
    assert processed == len(movies), f"lightrag processed={processed} expected={len(movies)}"
    print(
        f"Validated: {movie_count} movies, {processed} LightRAG docs, referential integrity OK",
        flush=True,
    )


@traceable(name="ingest_cmu_subset")
async def run_ingest(*, data_dir: Path, limit: int) -> None:
    """Execute the full hybrid ingest pipeline.

    Args:
        data_dir: Directory containing the three CMU TSV/TXT files.
        limit: Subset size (also overrides settings for this run).
    """
    summaries_path = data_dir / "plot_summaries.txt"
    metadata_path = data_dir / "movie.metadata.tsv"
    character_path = data_dir / "character.metadata.tsv"
    for path in (summaries_path, metadata_path, character_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}. Download CMU MovieSummaries into {data_dir}.")

    settings = get_settings()
    summaries = load_plot_summaries(summaries_path)
    metadata = load_movie_metadata(metadata_path)
    cast_by_movie = load_character_metadata(character_path)
    movies = select_subset(summaries, metadata, cast_by_movie, limit=limit)
    if not movies:
        raise RuntimeError("Subset selection produced zero movies")
    print(f"Selected {len(movies)} movies (limit={limit})", flush=True)

    await enrich_posters(movies, concurrency=settings.ingest_concurrency)
    posters = sum(1 for m in movies if m.poster_url)
    print(f"TMDB posters resolved: {posters}/{len(movies)}", flush=True)

    await upsert_projection(movies)
    print("Supabase projection upserted", flush=True)

    inserted = await insert_into_lightrag(movies, concurrency=settings.ingest_concurrency)
    print(f"LightRAG newly inserted: {inserted}", flush=True)

    await validate_load(movies)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for hybrid CMU ingestion."""
    parser = argparse.ArgumentParser(
        description="Ingest a CMU movie subset into LightRAG + Supabase."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Subset size (default: settings.subset_size / SUBSET_SIZE).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_DEFAULT_DATA_DIR,
        help=f"CMU MovieSummaries directory (default: {_DEFAULT_DATA_DIR}).",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    limit = args.limit if args.limit is not None else settings.subset_size
    asyncio.run(run_ingest(data_dir=args.data_dir, limit=limit))


if __name__ == "__main__":
    main()
