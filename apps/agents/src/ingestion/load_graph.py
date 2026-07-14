"""Batch-load the packaged Kaggle movie graph into Neo4j."""

from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Iterator, Mapping, Sequence
from importlib import resources
from typing import Any, LiteralString

from neo4j import Driver, ManagedTransaction

from agents.clients import get_neo4j_driver
from agents.settings import get_settings

DEFAULT_BATCH_SIZE = 200

DROP_OBSOLETE_SCHEMA: tuple[LiteralString, ...] = (
    "DROP CONSTRAINT movie_title IF EXISTS",
    "DROP CONSTRAINT person_name IF EXISTS",
)
CREATE_SCHEMA: tuple[LiteralString, ...] = (
    "CREATE CONSTRAINT movie_tmdb_id IF NOT EXISTS FOR (m:Movie) REQUIRE m.tmdbId IS UNIQUE",
    "CREATE CONSTRAINT person_tmdb_id IF NOT EXISTS FOR (p:Person) REQUIRE p.tmdbId IS UNIQUE",
    "CREATE CONSTRAINT genre_name IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE",
    "CREATE CONSTRAINT keyword_name IF NOT EXISTS FOR (k:Keyword) REQUIRE k.name IS UNIQUE",
    "CREATE INDEX movie_title IF NOT EXISTS FOR (m:Movie) ON (m.title)",
)

UPSERT_MOVIES: LiteralString = """
UNWIND $movies AS row
MERGE (m:Movie {tmdbId: row.tmdbId})
SET m.imdbId = row.imdbId,
    m.title = row.title,
    m.originalTitle = row.originalTitle,
    m.year = row.year,
    m.released = row.year,
    m.releaseDate = row.releaseDate,
    m.overview = row.overview,
    m.tagline = row.tagline,
    m.posterUrl = row.posterUrl,
    m.rating = row.rating,
    m.voteCount = row.voteCount,
    m.popularity = row.popularity,
    m.runtime = row.runtime
"""
UPSERT_CAST: LiteralString = """
UNWIND $movies AS movie
UNWIND movie.cast AS row
MERGE (p:Person {tmdbId: row.tmdbId})
SET p.name = row.name, p.profileUrl = row.profileUrl
WITH movie, row, p
MATCH (m:Movie {tmdbId: movie.tmdbId})
MERGE (p)-[r:ACTED_IN]->(m)
SET r.character = row.character,
    r.roles = CASE WHEN row.character = '' THEN [] ELSE [row.character] END,
    r.billingOrder = row.order
"""
UPSERT_CREW: dict[str, LiteralString] = {
    "directors": """
UNWIND $movies AS movie
UNWIND movie.directors AS row
MERGE (p:Person {tmdbId: row.tmdbId})
SET p.name = row.name, p.profileUrl = row.profileUrl
WITH movie, row, p
MATCH (m:Movie {tmdbId: movie.tmdbId})
MERGE (p)-[r:DIRECTED]->(m)
SET r.job = row.job
""",
    "writers": """
UNWIND $movies AS movie
UNWIND movie.writers AS row
MERGE (p:Person {tmdbId: row.tmdbId})
SET p.name = row.name, p.profileUrl = row.profileUrl
WITH movie, row, p
MATCH (m:Movie {tmdbId: movie.tmdbId})
MERGE (p)-[r:WROTE]->(m)
SET r.job = row.job
""",
    "producers": """
UNWIND $movies AS movie
UNWIND movie.producers AS row
MERGE (p:Person {tmdbId: row.tmdbId})
SET p.name = row.name, p.profileUrl = row.profileUrl
WITH movie, row, p
MATCH (m:Movie {tmdbId: movie.tmdbId})
MERGE (p)-[r:PRODUCED]->(m)
SET r.job = row.job
""",
}
UPSERT_GENRES: LiteralString = """
UNWIND $movies AS movie
UNWIND movie.genres AS name
MERGE (g:Genre {name: name})
WITH movie, g
MATCH (m:Movie {tmdbId: movie.tmdbId})
MERGE (m)-[:IN_GENRE]->(g)
"""
UPSERT_KEYWORDS: LiteralString = """
UNWIND $movies AS movie
UNWIND movie.keywords AS name
MERGE (k:Keyword {name: name})
WITH movie, k
MATCH (m:Movie {tmdbId: movie.tmdbId})
MERGE (m)-[:HAS_KEYWORD]->(k)
"""

COUNT_QUERY: LiteralString = """
CALL () {
  MATCH (m:Movie) RETURN 'Movie' AS key, count(m) AS count
  UNION ALL MATCH (p:Person) RETURN 'Person' AS key, count(p) AS count
  UNION ALL MATCH (g:Genre) RETURN 'Genre' AS key, count(g) AS count
  UNION ALL MATCH (k:Keyword) RETURN 'Keyword' AS key, count(k) AS count
  UNION ALL MATCH ()-[r:ACTED_IN]->() RETURN 'ACTED_IN' AS key, count(r) AS count
  UNION ALL MATCH ()-[r:DIRECTED]->() RETURN 'DIRECTED' AS key, count(r) AS count
  UNION ALL MATCH ()-[r:WROTE]->() RETURN 'WROTE' AS key, count(r) AS count
  UNION ALL MATCH ()-[r:PRODUCED]->() RETURN 'PRODUCED' AS key, count(r) AS count
  UNION ALL MATCH ()-[r:IN_GENRE]->() RETURN 'IN_GENRE' AS key, count(r) AS count
  UNION ALL MATCH ()-[r:HAS_KEYWORD]->() RETURN 'HAS_KEYWORD' AS key, count(r) AS count
}
RETURN key, count
"""


def read_bundle() -> dict[str, Any]:
    """Read and validate the compressed movie bundle from package resources.

    Returns:
        Parsed graph bundle.

    Raises:
        ValueError: If the packaged bundle has an unsupported structure.
    """
    asset = resources.files("agents").joinpath("data", "movies_subset.json.gz")
    with asset.open("rb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="rb") as compressed:
            bundle = json.load(compressed)
    if (
        not isinstance(bundle, dict)
        or bundle.get("schemaVersion") != 1
        or not isinstance(bundle.get("movies"), list)
        or not isinstance(bundle.get("manifest"), dict)
    ):
        raise ValueError("Unsupported movies_subset.json.gz bundle")
    return bundle


def batched(items: Sequence[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    """Yield fixed-size movie batches.

    Args:
        items: Movie records to split.
        size: Positive batch size.

    Yields:
        Consecutive movie record batches.
    """
    if size <= 0:
        raise ValueError("batch size must be positive")
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def _write_batch(tx: ManagedTransaction, movies: list[dict[str, Any]]) -> None:
    """Write one idempotent movie batch inside a Neo4j transaction."""
    tx.run(UPSERT_MOVIES, movies=movies).consume()
    tx.run(UPSERT_CAST, movies=movies).consume()
    for query in UPSERT_CREW.values():
        tx.run(query, movies=movies).consume()
    tx.run(UPSERT_GENRES, movies=movies).consume()
    tx.run(UPSERT_KEYWORDS, movies=movies).consume()


def _replace_graph(driver: Driver, database: str) -> None:
    """Delete all existing graph data in bounded transactions."""
    with driver.session(database=database) as session:
        session.run("MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS").consume()


def _ensure_safe_rerun(driver: Driver, database: str, replace_existing: bool) -> None:
    """Reject a merge-only run when obsolete ID-less seed nodes remain."""
    if replace_existing:
        _replace_graph(driver, database)
        return
    with driver.session(database=database) as session:
        obsolete = session.run(
            "MATCH (n) "
            "WHERE (n:Movie AND n.tmdbId IS NULL) OR (n:Person AND n.tmdbId IS NULL) "
            "RETURN count(n) AS count"
        ).single(strict=True)
    if obsolete is not None and int(obsolete["count"]) > 0:
        raise RuntimeError(
            "Obsolete sample nodes exist. Re-run with --replace-existing to delete them."
        )


def _apply_schema(driver: Driver, database: str) -> None:
    """Remove obsolete constraints and create the ID-stable schema."""
    with driver.session(database=database) as session:
        for statement in DROP_OBSOLETE_SCHEMA:
            session.run(statement).consume()
        for statement in CREATE_SCHEMA:
            session.run(statement).consume()


def _database_counts(driver: Driver, database: str) -> dict[str, int]:
    """Return supported node and relationship counts from Neo4j."""
    with driver.session(database=database) as session:
        return {str(record["key"]): int(record["count"]) for record in session.run(COUNT_QUERY)}


def _assert_manifest(counts: Mapping[str, int], manifest: Mapping[str, Any]) -> None:
    """Raise when loaded Neo4j counts disagree with the bundle manifest."""
    expected = {
        **manifest["nodeCounts"],
        **manifest["relationshipCounts"],
    }
    differences = {
        key: {"expected": int(value), "actual": counts.get(key, 0)}
        for key, value in expected.items()
        if counts.get(key, 0) != int(value)
    }
    if differences:
        raise RuntimeError(f"Neo4j counts do not match bundle manifest: {differences}")


def load_movies(*, replace_existing: bool = False, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
    """Load the packaged Kaggle movie graph into Neo4j.

    Args:
        replace_existing: Delete all current graph data before loading.
        batch_size: Movies written per transaction.

    Side effects:
        Deletes graph data only when explicitly requested, creates Neo4j schema,
        and idempotently writes all packaged graph records.

    Raises:
        RuntimeError: If replacement is required or loaded counts differ.
    """
    bundle = read_bundle()
    manifest = bundle["manifest"]
    if not manifest["limits"]["withinAuraFree"]:
        raise RuntimeError("Bundle exceeds configured Neo4j Aura Free limits")

    settings = get_settings()
    driver = get_neo4j_driver()
    _ensure_safe_rerun(driver, settings.neo4j_database, replace_existing)
    _apply_schema(driver, settings.neo4j_database)

    movies = bundle["movies"]
    total_batches = (len(movies) + batch_size - 1) // batch_size
    with driver.session(database=settings.neo4j_database) as session:
        for batch_number, movie_batch in enumerate(batched(movies, batch_size), start=1):
            session.execute_write(_write_batch, movie_batch)
            print(f"Loaded movie batch {batch_number}/{total_batches}")

    counts = _database_counts(driver, settings.neo4j_database)
    _assert_manifest(counts, manifest)
    print(json.dumps(counts, indent=2, sort_keys=True))
    print(f"Loaded and verified {len(movies)} movies.")


def _parser() -> argparse.ArgumentParser:
    """Create the graph-loader command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Explicitly delete the existing graph before loading the bundle.",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser


def main() -> None:
    """Run the package graph loader from the command line."""
    args = _parser().parse_args()
    load_movies(replace_existing=args.replace_existing, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
