"""Generate plot/tagline embeddings and build the Neo4j vector index."""

from neo4j_graphrag.embeddings import OpenAIEmbeddings
from neo4j_graphrag.indexes import create_vector_index

from agents.clients import get_neo4j_driver
from agents.settings import get_settings


def build_vector_index() -> None:
    """Embed movie plot/tagline text and create a Neo4j vector index.

    Side effects: writes an ``embedding`` property on Movie nodes and creates a
    vector index. Safe to re-run (index creation is IF NOT EXISTS).
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

    with driver.session(database=settings.neo4j_database) as session:
        rows = session.run(
            "MATCH (m:Movie) WHERE m.embedding IS NULL "
            "RETURN m.title AS title, coalesce(m.tagline, m.title) AS text"
        ).data()

    for row in rows:
        vector = embedder.embed_query(row["text"])
        with driver.session(database=settings.neo4j_database) as session:
            session.run(
                "MATCH (m:Movie {title: $title}) SET m.embedding = $embedding",
                title=row["title"],
                embedding=vector,
            )
    print(f"Embedded {len(rows)} movies and ensured vector index exists.")


if __name__ == "__main__":
    build_vector_index()
