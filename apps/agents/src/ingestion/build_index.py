"""Compose movie documents, batch-embed them, and rebuild Neo4j indexes."""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterator, Sequence
from typing import Any, LiteralString, cast

import tiktoken
from langchain_openai import OpenAIEmbeddings
from neo4j import Driver, ManagedTransaction
from pydantic import SecretStr
from tenacity import retry, stop_after_attempt, wait_exponential

from agents.clients import get_neo4j_driver
from agents.settings import get_settings

DEFAULT_EMBED_BATCH_SIZE = 100
MAX_OVERVIEW_CHARS = 1_500
_INDEX_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

EMBED_TEXT_QUERY: LiteralString = """
MATCH (m:Movie)
CALL (m) {
  OPTIONAL MATCH (a:Person)-[r:ACTED_IN]->(m)
  WITH a, r ORDER BY r.billingOrder ASC
  RETURN collect(
    CASE
      WHEN a IS NULL THEN null
      WHEN r.character IS NULL OR r.character = '' THEN a.name
      ELSE a.name + ' as ' + r.character
    END
  )[0..12] AS cast
}
CALL (m) {
  OPTIONAL MATCH (d:Person)-[:DIRECTED]->(m)
  RETURN collect(DISTINCT d.name)[0..5] AS directors
}
CALL (m) {
  OPTIONAL MATCH (w:Person)-[:WROTE]->(m)
  RETURN collect(DISTINCT w.name)[0..5] AS writers
}
CALL (m) {
  OPTIONAL MATCH (m)-[:IN_GENRE]->(g:Genre)
  RETURN collect(DISTINCT g.name) AS genres
}
CALL (m) {
  OPTIONAL MATCH (m)-[:HAS_KEYWORD]->(k:Keyword)
  RETURN collect(DISTINCT k.name)[0..10] AS keywords
}
RETURN m.tmdbId AS tmdbId,
       m.title AS title,
       m.year AS year,
       m.tagline AS tagline,
       m.overview AS overview,
       genres,
       keywords,
       cast,
       directors,
       writers
ORDER BY m.tmdbId
"""

WRITE_EMBEDDINGS_QUERY: LiteralString = """
UNWIND $rows AS row
MATCH (m:Movie {tmdbId: row.tmdbId})
SET m.embed_text = row.embedText,
    m.embedding = row.embedding
"""


def _non_empty(values: object) -> list[str]:
    """Return non-empty strings from a Neo4j collection value."""
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if value and str(value).strip()]


def _compose_document(row: dict[str, Any]) -> str:
    """Build a bounded embedding document from a movie graph neighborhood.

    Args:
        row: Movie properties and collected graph-neighborhood names.

    Returns:
        Natural-language document used for semantic retrieval.
    """
    title = str(row["title"])
    year = row.get("year")
    parts = [f"{title} ({year})" if year else title]
    if row.get("tagline"):
        parts.append(f"Tagline: {str(row['tagline']).strip()}")
    if row.get("overview"):
        overview = " ".join(str(row["overview"]).split())[:MAX_OVERVIEW_CHARS].rstrip()
        parts.append(f"Overview: {overview}")
    for field, prefix in (
        ("genres", "Genres: "),
        ("keywords", "Keywords: "),
        ("cast", "Starring: "),
        ("directors", "Directed by: "),
        ("writers", "Written by: "),
    ):
        values = _non_empty(row.get(field))
        if values:
            parts.append(prefix + ", ".join(values))
    return "\n".join(parts)


def _batches(items: Sequence[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    """Yield fixed-size embedding work batches."""
    if size <= 0:
        raise ValueError("batch size must be positive")
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def _token_count(documents: Sequence[str], model: str) -> int:
    """Return the exact tokenizer count for all embedding documents."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return sum(len(encoding.encode(document)) for document in documents)


def _safe_index_name(name: str) -> str:
    """Validate and return a trusted Neo4j index identifier."""
    if not _INDEX_IDENTIFIER.fullmatch(name):
        raise ValueError(f"Invalid Neo4j index name: {name!r}")
    return name


def _drop_indexes(driver: Driver, database: str, names: Sequence[str]) -> None:
    """Drop existing search indexes before changing dimensions/properties."""
    with driver.session(database=database) as session:
        for name in names:
            safe_name = _safe_index_name(name)
            query = cast(LiteralString, f"DROP INDEX {safe_name} IF EXISTS")
            session.run(query).consume()


def _create_indexes(
    driver: Driver,
    database: str,
    *,
    vector_name: str,
    fulltext_name: str,
    dimensions: int,
) -> None:
    """Create 1,536-dimensional vector and multi-property full-text indexes."""
    safe_vector = _safe_index_name(vector_name)
    safe_fulltext = _safe_index_name(fulltext_name)
    vector_query = cast(
        LiteralString,
        f"""
CREATE VECTOR INDEX {safe_vector} IF NOT EXISTS
FOR (m:Movie) ON (m.embedding)
OPTIONS {{indexConfig: {{
  `vector.dimensions`: {dimensions},
  `vector.similarity_function`: 'cosine'
}}}}
""",
    )
    fulltext_query = cast(
        LiteralString,
        f"""
CREATE FULLTEXT INDEX {safe_fulltext} IF NOT EXISTS
FOR (m:Movie) ON EACH [m.title, m.tagline, m.overview, m.embed_text]
""",
    )
    with driver.session(database=database) as session:
        session.run(vector_query).consume()
        session.run(fulltext_query).consume()
        session.run("CALL db.awaitIndexes($timeoutSeconds)", timeoutSeconds=300).consume()


def _write_embeddings(
    tx: ManagedTransaction,
    rows: list[dict[str, Any]],
) -> None:
    """Write one embedding batch to Movie nodes by stable TMDB ID."""
    tx.run(WRITE_EMBEDDINGS_QUERY, rows=rows).consume()


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=20), reraise=True)
def _embed_batch(
    embedder: OpenAIEmbeddings,
    documents: list[str],
) -> list[list[float]]:
    """Embed one document batch with bounded exponential retries."""
    return embedder.embed_documents(documents)


def build_vector_index(*, batch_size: int = DEFAULT_EMBED_BATCH_SIZE) -> None:
    """Batch-embed every movie and rebuild Neo4j search indexes.

    Args:
        batch_size: Number of documents sent and written per batch.

    Side effects:
        Calls the OpenAI embeddings API, writes movie vectors, and replaces the
        Neo4j vector/full-text indexes.
    """
    settings = get_settings()
    if settings.embedding_dimensions != 1_536:
        raise ValueError("text-embedding-3-small index must use 1,536 dimensions")
    driver = get_neo4j_driver()
    with driver.session(database=settings.neo4j_database) as session:
        rows = [dict(record) for record in session.run(EMBED_TEXT_QUERY)]
    documents = [_compose_document(row) for row in rows]
    token_count = _token_count(documents, settings.openai_embed_model)
    print(
        f"Prepared {len(documents)} documents with exactly {token_count} input tokens "
        f"for {settings.openai_embed_model}."
    )

    _drop_indexes(
        driver,
        settings.neo4j_database,
        (settings.vector_index_name, settings.fulltext_index_name),
    )
    embedder = OpenAIEmbeddings(
        model=settings.openai_embed_model,
        dimensions=settings.embedding_dimensions,
        api_key=SecretStr(settings.openai_api_key),
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        chunk_size=batch_size,
    )
    row_batches = list(_batches(rows, batch_size))
    document_batches = list(_batches([{"text": text} for text in documents], batch_size))
    total_batches = len(row_batches)
    with driver.session(database=settings.neo4j_database) as session:
        for batch_number, (row_batch, document_batch) in enumerate(
            zip(row_batches, document_batches, strict=True),
            start=1,
        ):
            texts = [item["text"] for item in document_batch]
            vectors = _embed_batch(embedder, texts)
            if len(vectors) != len(row_batch):
                raise RuntimeError("Embedding API returned an unexpected vector count")
            updates = [
                {
                    "tmdbId": row["tmdbId"],
                    "embedText": document,
                    "embedding": vector,
                }
                for row, document, vector in zip(row_batch, texts, vectors, strict=True)
            ]
            session.execute_write(_write_embeddings, updates)
            print(f"Embedded movie batch {batch_number}/{total_batches}")

    _create_indexes(
        driver,
        settings.neo4j_database,
        vector_name=settings.vector_index_name,
        fulltext_name=settings.fulltext_index_name,
        dimensions=settings.embedding_dimensions,
    )
    print(
        f"Composed, embedded, and indexed {len(rows)} movies "
        f"using {token_count} input tokens."
    )


def _parser() -> argparse.ArgumentParser:
    """Create the index-builder command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_EMBED_BATCH_SIZE)
    return parser


def main() -> None:
    """Run the batched index builder from the command line."""
    args = _parser().parse_args()
    build_vector_index(batch_size=args.batch_size)


if __name__ == "__main__":
    main()
