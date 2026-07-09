"""Compose per-movie documents, embed them, and build search indexes."""

from typing import Any

from neo4j_graphrag.embeddings import OpenAIEmbeddings
from neo4j_graphrag.indexes import create_fulltext_index, create_vector_index

from agents.clients import get_neo4j_driver
from agents.settings import get_settings

# Gather each movie plus its graph neighbourhood so the embedding text carries
# far more signal than the ~6-word tagline alone (cast, roles, directors,
# writers). This is the compose-from-graph embedding source.
EMBED_TEXT_QUERY = """
MATCH (m:Movie)
OPTIONAL MATCH (a:Person)-[r:ACTED_IN]->(m)
WITH m, collect(DISTINCT
    a.name + CASE
        WHEN r.roles IS NULL OR size(r.roles) = 0 THEN ''
        ELSE ' as ' + reduce(acc = '', role IN r.roles |
            CASE WHEN acc = '' THEN role ELSE acc + ', ' + role END)
    END) AS cast
OPTIONAL MATCH (d:Person)-[:DIRECTED]->(m)
WITH m, cast, collect(DISTINCT d.name) AS directors
OPTIONAL MATCH (w:Person)-[:WROTE]->(m)
WITH m, cast, directors, collect(DISTINCT w.name) AS writers
RETURN m.title AS title, m.tagline AS tagline, m.released AS released,
       cast, directors, writers
"""


def _compose_document(row: dict[str, Any]) -> str:
    """Build a single embedding document from a movie's graph neighbourhood.

    Args:
        row: A row from ``EMBED_TEXT_QUERY`` (title, tagline, released, cast,
            directors, writers).

    Returns:
        A composed natural-language document describing the movie.
    """
    released = row.get("released")
    parts: list[str] = [f"{row['title']} ({released})" if released else str(row["title"])]
    if row.get("tagline"):
        parts.append(f"Tagline: {row['tagline']}")
    if row.get("cast"):
        parts.append("Starring " + ", ".join(row["cast"]))
    if row.get("directors"):
        parts.append("Directed by " + ", ".join(row["directors"]))
    if row.get("writers"):
        parts.append("Written by " + ", ".join(row["writers"]))
    return ". ".join(parts)


def build_vector_index() -> None:
    """Compose per-movie documents, embed them, and build search indexes.

    Side effects: writes ``embed_text`` + ``embedding`` on every Movie node and
    creates a vector index and a full-text index. Re-embeds all movies (the
    embedding text source changed) and is safe to re-run (index creation does
    not fail if the index already exists).
    """
    settings = get_settings()
    driver = get_neo4j_driver()
    embedder = OpenAIEmbeddings(
        model=settings.openai_embed_model,
        api_key=settings.openai_api_key,
    )

    create_vector_index(
        driver,
        name=settings.vector_index_name,
        label="Movie",
        embedding_property="embedding",
        dimensions=settings.embedding_dimensions,
        similarity_fn="cosine",
        neo4j_database=settings.neo4j_database,
    )
    create_fulltext_index(
        driver,
        name=settings.fulltext_index_name,
        label="Movie",
        node_properties=["title", "tagline", "embed_text"],
        neo4j_database=settings.neo4j_database,
    )

    with driver.session(database=settings.neo4j_database) as session:
        rows = session.run(EMBED_TEXT_QUERY).data()

    for row in rows:
        document = _compose_document(row)
        vector = embedder.embed_query(document)
        with driver.session(database=settings.neo4j_database) as session:
            session.run(
                "MATCH (m:Movie {title: $title}) "
                "SET m.embed_text = $embed_text, m.embedding = $embedding",
                title=row["title"],
                embed_text=document,
                embedding=vector,
            )
    print(f"Composed, embedded, and indexed {len(rows)} movies.")


if __name__ == "__main__":
    build_vector_index()
