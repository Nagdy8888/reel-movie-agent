"""Retrieval functions + tools for the deterministic hybrid GraphRAG agent."""

import json
from functools import lru_cache
from typing import Any, LiteralString, cast

import neo4j
from langchain_core.tools import BaseTool, tool
from neo4j.exceptions import Neo4jError
from neo4j_graphrag.generation.prompts import Text2CypherTemplate
from neo4j_graphrag.retrievers import HybridCypherRetriever
from neo4j_graphrag.schema import get_schema
from neo4j_graphrag.types import RetrieverResultItem

from agents.clients import (
    get_embedder,
    get_neo4j_driver,
    get_text2cypher_llm,
    get_utility_llm,
)
from agents.prompts.system import RERANK_SYSTEM_V1, TEXT2CYPHER_EXAMPLES
from agents.safety import UnsafeCypherError, ensure_read_only, strip_cypher_fences
from agents.settings import get_settings

# Fallback schema, used ONLY if live introspection fails. The live schema
# (get_graph_schema) is preferred so the prompt can never drift from the data.
NEO4J_SCHEMA = (
    "Node labels:\n"
    "  Movie(title: string, released: int, tagline: string)\n"
    "  Person(name: string, born: int)\n"
    "Relationships:\n"
    "  (Person)-[:ACTED_IN {roles: list<string>}]->(Movie)\n"
    "  (Person)-[:DIRECTED]->(Movie)\n"
    "  (Person)-[:PRODUCED]->(Movie)\n"
    "  (Person)-[:WROTE]->(Movie)\n"
    "  (Person)-[:REVIEWED {summary: string, rating: int}]->(Movie)\n"
    "  (Person)-[:FOLLOWS]->(Person)"
)

# Graph-traversal step for hybrid semantic search: after vector + full-text
# search finds seed Movie nodes (bound as `node`), expand each into its
# connected context — cast (with roles), directors, writers, producers, and
# reviews — so the retriever returns graph-grounded neighbourhoods rather than
# isolated taglines. This is what makes the semantic path genuinely GraphRAG.
MOVIE_CONTEXT_QUERY = """
WITH node AS movie, score
OPTIONAL MATCH (a:Person)-[r:ACTED_IN]->(movie)
WITH movie, score, collect(DISTINCT
    a.name + CASE
        WHEN r.roles IS NULL OR size(r.roles) = 0 THEN ''
        ELSE ' as ' + reduce(acc = '', role IN r.roles |
            CASE WHEN acc = '' THEN role ELSE acc + ', ' + role END)
    END) AS cast
OPTIONAL MATCH (d:Person)-[:DIRECTED]->(movie)
WITH movie, score, cast, collect(DISTINCT d.name) AS directors
OPTIONAL MATCH (w:Person)-[:WROTE]->(movie)
WITH movie, score, cast, directors, collect(DISTINCT w.name) AS writers
OPTIONAL MATCH (p:Person)-[:PRODUCED]->(movie)
WITH movie, score, cast, directors, writers, collect(DISTINCT p.name) AS producers
OPTIONAL MATCH (rv:Person)-[rr:REVIEWED]->(movie)
WITH movie, score, cast, directors, writers, producers, collect(DISTINCT
    rv.name + ' rated ' + toString(rr.rating) + '/100: ' + rr.summary) AS reviews
RETURN
    'Movie: ' + movie.title
    + coalesce(' (' + toString(movie.released) + ')', '')
    + coalesce(' - tagline: "' + movie.tagline + '"', '')
    + CASE WHEN size(cast) > 0 THEN '\\nCast: ' + reduce(s = '', x IN cast |
        CASE WHEN s = '' THEN x ELSE s + '; ' + x END) ELSE '' END
    + CASE WHEN size(directors) > 0 THEN '\\nDirected by: ' + reduce(s = '', x IN directors |
        CASE WHEN s = '' THEN x ELSE s + ', ' + x END) ELSE '' END
    + CASE WHEN size(writers) > 0 THEN '\\nWritten by: ' + reduce(s = '', x IN writers |
        CASE WHEN s = '' THEN x ELSE s + ', ' + x END) ELSE '' END
    + CASE WHEN size(producers) > 0 THEN '\\nProduced by: ' + reduce(s = '', x IN producers |
        CASE WHEN s = '' THEN x ELSE s + ', ' + x END) ELSE '' END
    + CASE WHEN size(reviews) > 0 THEN '\\nReviews: ' + reduce(s = '', x IN reviews |
        CASE WHEN s = '' THEN x ELSE s + ' | ' + x END) ELSE '' END
    AS text, score
ORDER BY score DESC
"""

# Fallback recommendation query. Used only when both retrievers come up empty
# for a recommendation-style request (e.g. a bare "suggest a film to watch"
# that matches nothing specific). Returns the best-reviewed movies in the SAME
# text shape as MOVIE_CONTEXT_QUERY so downstream artifact parsing and the
# generate prompt work unchanged. This grounds open-ended recommendations in
# real graph movies instead of the fail-closed "no information" reply.
FALLBACK_MOVIES_QUERY = """
MATCH (movie:Movie)
OPTIONAL MATCH (:Person)-[rr:REVIEWED]->(movie)
WITH movie, avg(rr.rating) AS avg_rating, count(rr) AS review_count
OPTIONAL MATCH (a:Person)-[r:ACTED_IN]->(movie)
WITH movie, avg_rating, review_count, collect(DISTINCT
    a.name + CASE
        WHEN r.roles IS NULL OR size(r.roles) = 0 THEN ''
        ELSE ' as ' + reduce(acc = '', role IN r.roles |
            CASE WHEN acc = '' THEN role ELSE acc + ', ' + role END)
    END) AS cast
OPTIONAL MATCH (d:Person)-[:DIRECTED]->(movie)
WITH movie, avg_rating, review_count, cast, collect(DISTINCT d.name) AS directors
RETURN
    'Movie: ' + movie.title
    + coalesce(' (' + toString(movie.released) + ')', '')
    + coalesce(' - tagline: "' + movie.tagline + '"', '')
    + CASE WHEN size(cast) > 0 THEN '\\nCast: ' + reduce(s = '', x IN cast |
        CASE WHEN s = '' THEN x ELSE s + '; ' + x END) ELSE '' END
    + CASE WHEN size(directors) > 0 THEN '\\nDirected by: ' + reduce(s = '', x IN directors |
        CASE WHEN s = '' THEN x ELSE s + ', ' + x END) ELSE '' END
    AS text
ORDER BY review_count DESC, avg_rating DESC, movie.title
LIMIT $limit
"""

MAX_CYPHER_ATTEMPTS = 3


def _format_movie_context(record: neo4j.Record) -> RetrieverResultItem:
    """Turn a traversed movie record into a single grounding string.

    Args:
        record: A row from ``MOVIE_CONTEXT_QUERY`` exposing a ``text`` column.

    Returns:
        A retriever item whose content is the assembled movie neighbourhood.
    """
    return RetrieverResultItem(content=str(record.get("text", "")).strip())


@lru_cache(maxsize=1)
def get_graph_schema() -> str:
    """Return the live Neo4j schema string for Text2Cypher (cached).

    Introspects the database via ``neo4j_graphrag.schema.get_schema`` so the
    prompt schema can never drift from the loaded data. Falls back to the
    hand-written ``NEO4J_SCHEMA`` constant if introspection fails.

    Returns:
        A schema description string suitable for the Text2Cypher prompt.
    """
    try:
        return get_schema(get_neo4j_driver())
    except Exception:
        return NEO4J_SCHEMA


def _execute_read(query: LiteralString) -> list[dict[str, Any]]:
    """Execute a validated read-only Cypher query and return row dicts.

    Args:
        query: A Cypher statement already validated as read-only.

    Returns:
        The query result rows as a list of dictionaries.
    """
    settings = get_settings()
    driver = get_neo4j_driver()

    def _read(tx: neo4j.ManagedTransaction) -> list[dict[str, Any]]:
        """Run the query inside a managed read transaction."""
        return [dict(record) for record in tx.run(query)]

    with driver.session(database=settings.neo4j_database) as session:
        return session.execute_read(_read)


def run_graph_query(question: str) -> str:
    """Answer a structured question via robust read-only Text2Cypher.

    Uses an introspected schema plus few-shot examples, then a bounded
    self-correction loop: on a Neo4j error or an empty result the failure is
    fed back to the LLM to repair the query. Every generated query is validated
    read-only (a write clause aborts the attempt) and executed in a read
    transaction.

    Args:
        question: The user's natural-language question.

    Returns:
        Formatted result rows, or an empty string if nothing could be answered.
    """
    llm = get_text2cypher_llm()
    schema = get_graph_schema()

    feedback = ""
    records: list[dict[str, Any]] = []
    for _ in range(MAX_CYPHER_ATTEMPTS):
        query_text = question if not feedback else f"{question}\n\n{feedback}"
        prompt = Text2CypherTemplate().format(
            schema=schema,
            examples=TEXT2CYPHER_EXAMPLES,
            query_text=query_text,
        )
        raw = strip_cypher_fences(str(llm.invoke(prompt).content))
        try:
            cypher = ensure_read_only(raw)
        except UnsafeCypherError:
            # Never retry a write clause into execution; fail closed.
            return ""
        read_query = cast(LiteralString, cypher)

        try:
            records = _execute_read(read_query)
        except Neo4jError as exc:
            feedback = (
                "The previous Cypher failed with this error. Fix it and return "
                f"only a valid read-only Cypher statement. Error: {exc.message}"
            )
            continue
        if records:
            return "\n".join(str(record) for record in records)
        feedback = (
            "The previous query returned no rows. Try a different pattern, "
            "relationship direction, or property spelling."
        )
    return "\n".join(str(record) for record in records)


def run_semantic_search(question: str) -> list[str]:
    """Answer a fuzzy/plot/theme question via graph-augmented hybrid search.

    Vector and full-text (BM25) search find seed Movie nodes; the traversal in
    ``MOVIE_CONTEXT_QUERY`` expands each into its cast, directors, writers,
    producers, and reviews.

    Args:
        question: The user's natural-language question.

    Returns:
        A list of graph-grounded movie neighbourhood strings (possibly empty).
    """
    settings = get_settings()
    retriever = HybridCypherRetriever(
        get_neo4j_driver(),
        vector_index_name=settings.vector_index_name,
        fulltext_index_name=settings.fulltext_index_name,
        retrieval_query=MOVIE_CONTEXT_QUERY,
        embedder=get_embedder(),
        result_formatter=_format_movie_context,
        neo4j_database=settings.neo4j_database,
    )
    result = retriever.search(query_text=question, top_k=settings.retrieval_top_k)
    return [str(item.content) for item in result.items if str(item.content).strip()]


def run_recommendation_fallback(limit: int | None = None) -> list[str]:
    """Return a few well-reviewed movies as fallback recommendation context.

    Used only when a recommendation request matched nothing specific, so the
    agent can still suggest real movies from the graph instead of failing
    closed. Read-only: runs a fixed, parameterised query in a read transaction.

    Args:
        limit: Maximum number of movies to return. Defaults to the configured
            ``retrieval_top_k`` when not provided.

    Returns:
        A list of graph-grounded movie neighbourhood strings (possibly empty).
    """
    settings = get_settings()
    top_k = limit if limit is not None else settings.retrieval_top_k
    driver = get_neo4j_driver()

    def _read(tx: neo4j.ManagedTransaction) -> list[str]:
        """Fetch the best-reviewed movies inside a read transaction."""
        result = tx.run(cast(LiteralString, FALLBACK_MOVIES_QUERY), limit=top_k)
        return [str(record.get("text", "")).strip() for record in result]

    with driver.session(database=settings.neo4j_database) as session:
        rows = session.execute_read(_read)
    return [row for row in rows if row]


def run_rerank(question: str, candidates: list[str]) -> list[str]:
    """Reorder candidates by relevance to the question, keeping the top-k.

    Fail-open: on any LLM or parse error the original candidates are returned
    truncated to ``rerank_top_k``, so reranking can never block an answer.

    Args:
        question: The user's natural-language question.
        candidates: Retrieved context passages to reorder.

    Returns:
        The most relevant passages, best first, at most ``rerank_top_k``.
    """
    settings = get_settings()
    if not candidates:
        return []
    numbered = "\n\n".join(f"[{i}] {chunk}" for i, chunk in enumerate(candidates))
    prompt = RERANK_SYSTEM_V1.format(
        top_k=settings.rerank_top_k,
        question=question,
        candidates=numbered,
    )
    try:
        raw = strip_cypher_fences(str(get_utility_llm().invoke(prompt).content))
        order = json.loads(raw)
        picked = [
            candidates[i]
            for i in order
            if isinstance(i, int) and 0 <= i < len(candidates)
        ]
        if picked:
            return picked[: settings.rerank_top_k]
    except (ValueError, TypeError):
        pass
    return candidates[: settings.rerank_top_k]


@tool
def graph_query(question: str) -> str:
    """Answer a structured movie question via read-only Text2Cypher.

    Use for precise facts: who acted in / directed a movie, release years,
    counts. Generated Cypher is validated read-only before execution.
    """
    return run_graph_query(question) or "No results."


@tool
def semantic_search(question: str) -> str:
    """Answer a fuzzy/plot/theme movie question via graph-augmented hybrid search.

    Use for questions about what a movie is *about* rather than exact facts.
    Vector and full-text search find movies, then a graph traversal expands each
    match into its cast, directors, writers, producers, and reviews.
    """
    return "\n\n".join(run_semantic_search(question)) or "No results."


TOOLS: list[BaseTool] = [graph_query, semantic_search]
