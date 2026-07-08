"""Retrieval tools bound to the agent (read-only)."""

from typing import Any, LiteralString, cast

import neo4j
from langchain_core.tools import BaseTool, tool
from neo4j_graphrag.generation.prompts import Text2CypherTemplate
from neo4j_graphrag.retrievers import VectorRetriever

from agents.clients import get_embedder, get_neo4j_driver, get_text2cypher_llm
from agents.safety import ensure_read_only, strip_cypher_fences
from agents.settings import get_settings

NEO4J_SCHEMA = (
    "Node labels: Movie(title, released, tagline), Person(name, born). "
    "Relationships: (Person)-[:ACTED_IN]->(Movie), (Person)-[:DIRECTED]->(Movie)."
)


@tool
def graph_query(question: str) -> str:
    """Answer a structured movie question via read-only Text2Cypher.

    Use for precise facts: who acted in / directed a movie, release years,
    counts. Generated Cypher is validated read-only before execution.
    """
    settings = get_settings()
    driver = get_neo4j_driver()
    llm = get_text2cypher_llm()
    prompt = Text2CypherTemplate().format(
        schema=NEO4J_SCHEMA,
        examples="",
        query_text=question,
    )
    # Generate first, then validate — Text2CypherRetriever executes internally
    # and cannot be guarded between generation and run.
    cypher = ensure_read_only(strip_cypher_fences(llm.invoke(prompt).content))
    # Safe: ensure_read_only rejected write clauses; driver still uses execute_read.
    read_query = cast(LiteralString, cypher)

    def _read(tx: neo4j.ManagedTransaction) -> list[dict[str, Any]]:
        """Execute the validated Cypher inside a read transaction."""
        return [dict(record) for record in tx.run(read_query)]

    with driver.session(database=settings.neo4j_database) as session:
        records = session.execute_read(_read)
    return "\n".join(str(record) for record in records) or "No results."


@tool
def semantic_search(question: str) -> str:
    """Answer a fuzzy/plot/theme movie question via vector search.

    Use for questions about what a movie is *about* rather than exact facts.
    """
    settings = get_settings()
    driver = get_neo4j_driver()
    retriever = VectorRetriever(
        driver,
        index_name=settings.vector_index_name,
        embedder=get_embedder(),
        return_properties=["title", "tagline"],
        neo4j_database=settings.neo4j_database,
    )
    result = retriever.search(query_text=question, top_k=5)
    return "\n".join(str(item.content) for item in result.items) or "No results."


TOOLS: list[BaseTool] = [graph_query, semantic_search]
