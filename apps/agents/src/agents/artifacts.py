"""Structured sources and graph payloads derived from retrieval candidates."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Literal, LiteralString, TypedDict, cast
from urllib.parse import quote

import neo4j

from agents.clients import get_neo4j_driver
from agents.settings import get_settings

_MOVIE_LINE = re.compile(
    r"^Movie:\s+(.+?)(?:\s+\((\d{4})\))?\s+\[TMDB ID:\s*(\d+)\]",
    re.MULTILINE,
)
_TITLE_IN_RECORD = re.compile(r"['\"]?(?:m\.)?title['\"]?\s*:\s*['\"]([^'\"]+)['\"]", re.I)
_TMDB_ID_IN_RECORD = re.compile(r"['\"]?(?:m\.)?tmdbId['\"]?\s*:\s*(\d+)", re.I)
_DIRECTED_BY = re.compile(r"Directed by:\s*(.+?)(?:\n|$)", re.I)
_CAST_LINE = re.compile(r"Cast:\s*(.+?)(?:\n|$)", re.I)
_POSTER_LINE = re.compile(r"Poster URL:\s*(https://\S+)", re.I)
_TAGLINE_LINE = re.compile(r"Tagline:\s*(.+?)(?:\n|$)", re.I)

_MAX_GRAPH_MOVIES = 40
_MAX_SOURCE_TAGS = 4


class SourceArtifact(TypedDict):
    """A movie source card emitted to the frontend."""

    id: str
    title: str
    subtitle: str | None
    year: str | None
    poster_url: str | None
    tags: list[str]


class GraphNodeArtifact(TypedDict):
    """A node in the explored subgraph."""

    id: str
    label: str
    type: Literal["Movie", "Person", "Genre", "Keyword"]


class GraphLinkArtifact(TypedDict):
    """A relationship edge in the explored subgraph."""

    source: str
    target: str
    label: str


class GraphArtifact(TypedDict):
    """Nodes and links for the graph panel."""

    nodes: list[GraphNodeArtifact]
    links: list[GraphLinkArtifact]


class RetrievalArtifacts(TypedDict):
    """Sources and graph neighbourhood for one retrieval turn."""

    sources: list[SourceArtifact]
    graph: GraphArtifact


def _movie_id(tmdb_id: int) -> str:
    """Return a stable movie node ID from its TMDB ID."""
    return f"movie:{tmdb_id}"


def _person_id(tmdb_id: int) -> str:
    """Return a stable person node ID from its TMDB ID."""
    return f"person:{tmdb_id}"


def _named_node_id(kind: str, name: str) -> str:
    """Return a collision-safe ID for a unique named graph node."""
    return f"{kind.lower()}:{quote(name.casefold(), safe='')}"


def _parse_tags(chunk: str) -> list[str]:
    """Extract short role tags from a movie neighbourhood chunk."""
    tags: list[str] = []
    directed = _DIRECTED_BY.search(chunk)
    if directed:
        names = [n.strip() for n in directed.group(1).split(",") if n.strip()]
        tags.extend(names[:2])
    cast_match = _CAST_LINE.search(chunk)
    if cast_match:
        cast_names = [n.split(" as ")[0].strip() for n in cast_match.group(1).split(";")]
        tags.extend(cast_names[:2])
    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tag)
        if len(deduped) >= _MAX_SOURCE_TAGS:
            break
    return deduped


def extract_movie_titles(candidates: list[str]) -> list[str]:
    """Collect unique movie titles referenced in retrieval candidate text.

    Args:
        candidates: Raw retrieval passages from graph query and semantic search.

    Returns:
        De-duplicated movie titles in first-seen order.
    """
    titles: list[str] = []
    seen: set[str] = set()
    for chunk in candidates:
        for match in _MOVIE_LINE.finditer(chunk):
            title = match.group(1).strip()
            key = title.lower()
            if key and key not in seen:
                seen.add(key)
                titles.append(title)
        for match in _TITLE_IN_RECORD.finditer(chunk):
            title = match.group(1).strip()
            key = title.lower()
            if key and key not in seen:
                seen.add(key)
                titles.append(title)
    return titles


def extract_movie_ids(candidates: list[str]) -> list[int]:
    """Collect unique TMDB movie IDs referenced in retrieval candidates.

    Args:
        candidates: Raw retrieval passages from graph query and semantic search.

    Returns:
        De-duplicated TMDB IDs in first-seen order.
    """
    movie_ids: list[int] = []
    seen: set[int] = set()
    for chunk in candidates:
        for match in _MOVIE_LINE.finditer(chunk):
            movie_id = int(match.group(3))
            if movie_id not in seen:
                seen.add(movie_id)
                movie_ids.append(movie_id)
        for match in _TMDB_ID_IN_RECORD.finditer(chunk):
            movie_id = int(match.group(1))
            if movie_id not in seen:
                seen.add(movie_id)
                movie_ids.append(movie_id)
    return movie_ids


def sources_from_candidates(candidates: list[str]) -> list[SourceArtifact]:
    """Build source cards from semantic movie neighbourhood chunks.

    Args:
        candidates: Retrieval passages, including ``Movie:`` neighbourhood text.

    Returns:
        De-duplicated source cards ordered by appearance.
    """
    sources: list[SourceArtifact] = []
    seen: set[int] = set()
    for chunk in candidates:
        match = _MOVIE_LINE.search(chunk)
        if not match:
            continue
        title = match.group(1).strip()
        movie_id = int(match.group(3))
        if not title or movie_id in seen:
            continue
        seen.add(movie_id)
        year = match.group(2)
        tagline_match = _TAGLINE_LINE.search(chunk)
        poster_match = _POSTER_LINE.search(chunk)
        sources.append(
            SourceArtifact(
                id=_movie_id(movie_id),
                title=title,
                subtitle=tagline_match.group(1).strip() if tagline_match else None,
                year=year,
                poster_url=poster_match.group(1) if poster_match else None,
                tags=_parse_tags(chunk),
            )
        )
    return sources


_RESOLVE_MOVIE_IDS_QUERY = """
UNWIND range(0, size($titles) - 1) AS position
WITH position, $titles[position] AS requested_title
MATCH (m:Movie)
WHERE toLower(m.title) = toLower(requested_title)
RETURN position, m.tmdbId AS tmdb_id
ORDER BY position, m.tmdbId
"""

_ARTIFACT_QUERY = """
UNWIND range(0, size($movie_ids) - 1) AS position
WITH position, $movie_ids[position] AS movie_id
MATCH (m:Movie {tmdbId: movie_id})
CALL (m) {
    OPTIONAL MATCH (a:Person)-[r:ACTED_IN]->(m)
    WITH a, r ORDER BY r.billingOrder
    RETURN collect(a.name)[0..2] AS cast
}
CALL (m) {
    OPTIONAL MATCH (d:Person)-[:DIRECTED]->(m)
    RETURN collect(DISTINCT d.name)[0..2] AS directors
}
OPTIONAL MATCH (m)-[r]-(neighbor)
WHERE type(r) IN [
    'ACTED_IN', 'DIRECTED', 'PRODUCED', 'WROTE', 'IN_GENRE', 'HAS_KEYWORD'
]
RETURN position,
       m.tmdbId AS tmdb_id,
       m.title AS title,
       m.year AS year,
       m.tagline AS tagline,
       m.posterUrl AS poster_url,
       cast,
       directors,
       labels(neighbor) AS neighbor_labels,
       neighbor.tmdbId AS neighbor_tmdb_id,
       neighbor.title AS neighbor_title,
       neighbor.name AS neighbor_name,
       type(r) AS rel_type,
       CASE WHEN r IS NULL THEN null ELSE startNode(r) = m END AS movie_is_source
ORDER BY position
"""


def _resolve_movie_ids(titles: list[str]) -> list[int]:
    """Resolve title-only graph facts to stable TMDB IDs.

    Args:
        titles: Movie titles parsed from structured Text2Cypher rows.

    Returns:
        Matching TMDB IDs in candidate order, including distinct duplicate-title
        movies. Returns an empty list when Neo4j is unavailable.
    """
    if not titles:
        return []

    def _read(tx: neo4j.ManagedTransaction) -> list[int]:
        """Resolve titles inside a managed read transaction."""
        result = tx.run(_RESOLVE_MOVIE_IDS_QUERY, titles=titles[:_MAX_GRAPH_MOVIES])
        return [int(record["tmdb_id"]) for record in result]

    try:
        settings = get_settings()
        driver = get_neo4j_driver()
        with driver.session(database=settings.neo4j_database) as session:
            return session.execute_read(_read)
    except Exception:
        return []


_FULL_GRAPH_RELATIONSHIPS = [
    "ACTED_IN",
    "DIRECTED",
    "PRODUCED",
    "WROTE",
    "IN_GENRE",
    "HAS_KEYWORD",
]

_FULL_GRAPH_NODES_QUERY = """
MATCH (n)
WHERE n:Movie OR n:Person OR n:Genre OR n:Keyword
RETURN labels(n) AS labels,
       n.tmdbId AS tmdb_id,
       n.title AS title,
       n.name AS name
"""

_FULL_GRAPH_LINKS_QUERY = """
MATCH (source)-[rel]->(target)
WHERE (source:Movie OR source:Person OR source:Genre OR source:Keyword)
  AND (target:Movie OR target:Person OR target:Genre OR target:Keyword)
  AND type(rel) IN $relationship_types
RETURN labels(source) AS source_labels,
       source.tmdbId AS source_tmdb_id,
       source.title AS source_title,
       source.name AS source_name,
       labels(target) AS target_labels,
       target.tmdbId AS target_tmdb_id,
       target.title AS target_title,
       target.name AS target_name,
       type(rel) AS rel_type
"""


def _node_artifact(
    labels: list[str],
    tmdb_id: object,
    title: object,
    name: object,
) -> GraphNodeArtifact | None:
    """Build a graph node artifact from a Neo4j node row.

    Args:
        labels: Neo4j labels attached to the node.
        tmdb_id: Stable TMDB ID for Movie and Person nodes.
        title: Movie title value when present.
        name: Person, Genre, or Keyword name value when present.

    Returns:
        A normalized graph node artifact, or ``None`` when required data is
        missing.
    """
    if "Movie" in labels:
        label = str(title or "").strip()
        if not label or not isinstance(tmdb_id, int):
            return None
        return GraphNodeArtifact(id=_movie_id(tmdb_id), label=label, type="Movie")
    if "Person" in labels:
        label = str(name or "").strip()
        if not label or not isinstance(tmdb_id, int):
            return None
        return GraphNodeArtifact(id=_person_id(tmdb_id), label=label, type="Person")
    for node_type in ("Genre", "Keyword"):
        if node_type in labels:
            label = str(name or "").strip()
            if not label:
                return None
            return GraphNodeArtifact(
                id=_named_node_id(node_type, label),
                label=label,
                type=cast(Literal["Genre", "Keyword"], node_type),
            )
    return None


def artifacts_from_movie_ids(movie_ids: list[int]) -> RetrievalArtifacts:
    """Load source cards and graph neighborhoods in one read-only query.

    Args:
        movie_ids: Stable TMDB movie IDs to hydrate and expand in Neo4j.

    Returns:
        Source cards and graph data for the focused answer view. Both are empty
        when Neo4j is unavailable or no rows match.
    """
    empty: GraphArtifact = {"nodes": [], "links": []}
    if not movie_ids:
        return RetrievalArtifacts(sources=[], graph=empty)

    sources: dict[str, SourceArtifact] = {}
    nodes: dict[str, GraphNodeArtifact] = {}
    links: list[GraphLinkArtifact] = []
    link_keys: set[str] = set()

    def _read(tx: neo4j.ManagedTransaction) -> list[dict[str, Any]]:
        """Hydrate source metadata and neighborhoods in one transaction."""
        result = tx.run(_ARTIFACT_QUERY, movie_ids=movie_ids[:_MAX_GRAPH_MOVIES])
        return [dict(record) for record in result]

    try:
        settings = get_settings()
        driver = get_neo4j_driver()
        with driver.session(database=settings.neo4j_database) as session:
            rows = session.execute_read(_read)
    except Exception:
        return RetrievalArtifacts(sources=[], graph=empty)

    for row in rows:
        movie_id = row.get("tmdb_id")
        movie_title = str(row.get("title") or "").strip()
        if not isinstance(movie_id, int) or not movie_title:
            continue
        movie_node_id = _movie_id(movie_id)
        if movie_node_id not in sources:
            tags: list[str] = []
            seen_tags: set[str] = set()
            for name in [*(row.get("directors") or []), *(row.get("cast") or [])]:
                tag = str(name or "").strip()
                key = tag.casefold()
                if not tag or key in seen_tags:
                    continue
                seen_tags.add(key)
                tags.append(tag)
                if len(tags) >= _MAX_SOURCE_TAGS:
                    break
            year = row.get("year")
            sources[movie_node_id] = SourceArtifact(
                id=movie_node_id,
                title=movie_title,
                subtitle=str(row["tagline"]).strip() if row.get("tagline") else None,
                year=str(year) if isinstance(year, int) else None,
                poster_url=(str(row["poster_url"]).strip() if row.get("poster_url") else None),
                tags=tags,
            )
        movie = _node_artifact(
            ["Movie"],
            movie_id,
            movie_title,
            None,
        )
        if movie is None:
            continue
        nodes.setdefault(movie["id"], movie)
        neighbor = _node_artifact(
            list(row.get("neighbor_labels") or []),
            row.get("neighbor_tmdb_id"),
            row.get("neighbor_title"),
            row.get("neighbor_name"),
        )
        rel_type = str(row.get("rel_type") or "").strip()
        if neighbor is None or not rel_type:
            continue
        nodes.setdefault(neighbor["id"], neighbor)
        if row.get("movie_is_source"):
            source_id, target_id = movie["id"], neighbor["id"]
        else:
            source_id, target_id = neighbor["id"], movie["id"]
        link_key = f"{source_id}->{target_id}:{rel_type}"
        if link_key in link_keys:
            continue
        link_keys.add(link_key)
        links.append(
            GraphLinkArtifact(
                source=source_id,
                target=target_id,
                label=rel_type.replace("_", " ").title(),
            )
        )

    return RetrievalArtifacts(
        sources=list(sources.values()),
        graph=GraphArtifact(nodes=list(nodes.values()), links=links),
    )


@lru_cache(maxsize=1)
def _full_graph_cached() -> GraphArtifact:
    """Load and cache a successful full-graph snapshot from Neo4j.

    Raises:
        Exception: Propagates Neo4j/driver failures so callers can avoid caching
            empty fallbacks.
    """
    settings = get_settings()
    driver = get_neo4j_driver()
    nodes: dict[str, GraphNodeArtifact] = {}
    links: list[GraphLinkArtifact] = []
    link_keys: set[str] = set()

    def _read(tx: neo4j.ManagedTransaction) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Run full graph node and relationship queries inside a read transaction."""
        node_rows = [
            dict(record) for record in tx.run(cast(LiteralString, _FULL_GRAPH_NODES_QUERY))
        ]
        link_rows = [
            dict(record)
            for record in tx.run(
                cast(LiteralString, _FULL_GRAPH_LINKS_QUERY),
                relationship_types=_FULL_GRAPH_RELATIONSHIPS,
            )
        ]
        return node_rows, link_rows

    with driver.session(database=settings.neo4j_database) as session:
        node_rows, link_rows = session.execute_read(_read)

    for row in node_rows:
        node = _node_artifact(
            list(row.get("labels") or []),
            row.get("tmdb_id"),
            row.get("title"),
            row.get("name"),
        )
        if node is not None:
            nodes[node["id"]] = node

    for row in link_rows:
        source = _node_artifact(
            list(row.get("source_labels") or []),
            row.get("source_tmdb_id"),
            row.get("source_title"),
            row.get("source_name"),
        )
        target = _node_artifact(
            list(row.get("target_labels") or []),
            row.get("target_tmdb_id"),
            row.get("target_title"),
            row.get("target_name"),
        )
        rel_type = str(row.get("rel_type") or "").strip()
        if source is None or target is None or not rel_type:
            continue
        nodes.setdefault(source["id"], source)
        nodes.setdefault(target["id"], target)
        link_key = f"{source['id']}->{target['id']}:{rel_type}"
        if link_key in link_keys:
            continue
        link_keys.add(link_key)
        links.append(
            GraphLinkArtifact(
                source=source["id"],
                target=target["id"],
                label=rel_type.replace("_", " ").title(),
            )
        )

    return GraphArtifact(nodes=list(nodes.values()), links=links)


def full_graph() -> GraphArtifact:
    """Load the complete read-only movie knowledge graph.

    Args:
        None.

    Returns:
        Every supported Movie, Person, Genre, and Keyword node and relationship
        in Neo4j, normalized with stable IDs. Returns an empty graph if Neo4j is
        unavailable. Failures and empty snapshots are not cached.
    """
    empty: GraphArtifact = {"nodes": [], "links": []}
    try:
        graph = _full_graph_cached()
    except Exception:
        return empty
    if not graph["nodes"]:
        _full_graph_cached.cache_clear()
    return graph


full_graph.cache_clear = _full_graph_cached.cache_clear  # type: ignore[attr-defined]


def build_retrieval_artifacts(candidates: list[str]) -> RetrievalArtifacts:
    """Derive frontend sources and graph data from retrieval candidates.

    Args:
        candidates: Final reranked retrieval passages for the current turn.

    Returns:
        Structured sources and graph neighbourhood for the right pane.
    """
    movie_ids = extract_movie_ids(candidates)
    seen_ids = set(movie_ids)
    titles = extract_movie_titles(candidates)
    if len(movie_ids) < len(titles):
        for movie_id in _resolve_movie_ids(titles):
            if movie_id not in seen_ids and len(movie_ids) < _MAX_GRAPH_MOVIES:
                movie_ids.append(movie_id)
                seen_ids.add(movie_id)
    artifacts = artifacts_from_movie_ids(movie_ids)
    sources = artifacts["sources"]
    if not sources:
        sources = sources_from_candidates(candidates)
    return RetrievalArtifacts(sources=sources, graph=artifacts["graph"])


def cited_titles_from_answer(answer: str, available_titles: list[str]) -> list[str]:
    """Return movie titles from ``available_titles`` that appear in the answer.

    Args:
        answer: The assistant's final grounded reply for the turn.
        available_titles: Movie titles from the retrieval source cards.

    Returns:
        Cited titles in the order they first appear in ``answer``.
    """
    answer_lower = _normalized_title_text(answer)
    matches: list[tuple[int, str]] = []
    seen: set[str] = set()
    for title in available_titles:
        key = _normalized_title_text(title)
        if key in seen:
            continue
        position = answer_lower.find(key)
        if position >= 0:
            matches.append((position, title))
            seen.add(key)
    matches.sort(key=lambda item: item[0])
    return [title for _, title in matches]


def _normalized_title_text(value: str) -> str:
    """Return lowercase title text with punctuation collapsed to spaces."""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def filter_graph_by_titles(graph: GraphArtifact, titles: set[str]) -> GraphArtifact:
    """Keep only nodes and links for the cited movie titles.

    Args:
        graph: Full retrieval subgraph for the turn.
        titles: Movie titles cited in the assistant answer.

    Returns:
        A subgraph containing cited movies and their connected people.
    """
    if not titles:
        return {"nodes": [], "links": []}
    title_keys = {_normalized_title_text(title) for title in titles}
    cited_movie_ids = {
        node["id"]
        for node in graph["nodes"]
        if node["type"] == "Movie" and _normalized_title_text(node["label"]) in title_keys
    }
    if not cited_movie_ids:
        return {"nodes": [], "links": []}
    kept_node_ids = set(cited_movie_ids)
    for link in graph["links"]:
        if link["target"] in cited_movie_ids:
            kept_node_ids.add(link["source"])
        if link["source"] in cited_movie_ids:
            kept_node_ids.add(link["target"])
    return GraphArtifact(
        nodes=[node for node in graph["nodes"] if node["id"] in kept_node_ids],
        links=[
            link
            for link in graph["links"]
            if link["target"] in cited_movie_ids or link["source"] in cited_movie_ids
        ],
    )


def filter_artifacts_by_answer(
    sources: list[SourceArtifact],
    graph: GraphArtifact,
    answer: str,
) -> RetrievalArtifacts:
    """Align the right pane with movies actually cited in the assistant answer.

    Retrieval may return several candidate movies, but the generator can
    recommend or discuss only a subset (for example, one film when the user
    asks for a single suggestion). The right pane should reflect the answer,
    not the full retrieval pool.

    Args:
        sources: Source cards built from retrieval candidates.
        graph: Subgraph built from retrieval candidates.
        answer: The assistant's final grounded reply for the turn.

    Returns:
        Filtered sources and graph. When no cited title matches, the original
        artifacts are returned unchanged so factual answers still show context.
    """
    available = [cast(str, source["title"]) for source in sources]
    seen = {_normalized_title_text(title) for title in available}
    for node in graph["nodes"]:
        if node["type"] != "Movie":
            continue
        title = cast(str, node["label"])
        key = _normalized_title_text(title)
        if key in seen:
            continue
        seen.add(key)
        available.append(title)
    cited = cited_titles_from_answer(answer, available)
    if not cited:
        return RetrievalArtifacts(sources=sources, graph=graph)
    cited_set = set(cited)
    title_order = {_normalized_title_text(title): index for index, title in enumerate(cited)}
    filtered_sources = sorted(
        [source for source in sources if _normalized_title_text(source["title"]) in title_order],
        key=lambda source: title_order[_normalized_title_text(source["title"])],
    )
    return RetrievalArtifacts(
        sources=filtered_sources,
        graph=filter_graph_by_titles(graph, cited_set),
    )
