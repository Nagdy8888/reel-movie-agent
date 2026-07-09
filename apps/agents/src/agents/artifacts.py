"""Structured sources and graph payloads derived from retrieval candidates."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Literal, LiteralString, TypedDict, cast

import neo4j

from agents.clients import get_neo4j_driver
from agents.posters import poster_url_for_title
from agents.settings import get_settings

_MOVIE_LINE = re.compile(
    r"^Movie:\s+(.+?)(?:\s+\((\d{4})\))?(?:\s+-\s+tagline:|\s*$)",
    re.MULTILINE,
)
_TITLE_IN_RECORD = re.compile(r"['\"]?(?:m\.)?title['\"]?\s*:\s*['\"]([^'\"]+)['\"]", re.I)
_DIRECTED_BY = re.compile(r"Directed by:\s*(.+?)(?:\n|$)", re.I)
_CAST_LINE = re.compile(r"Cast:\s*(.+?)(?:\n|$)", re.I)

_MAX_GRAPH_MOVIES = 5
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
    type: Literal["Movie", "Person"]


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


def _slug(value: str) -> str:
    """Return a stable lowercase id fragment from a display label."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _movie_id(title: str) -> str:
    """Return a stable movie node id."""
    return f"movie:{_slug(title)}"


def _person_id(name: str) -> str:
    """Return a stable person node id."""
    return f"person:{_slug(name)}"


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


def sources_from_candidates(candidates: list[str]) -> list[SourceArtifact]:
    """Build source cards from semantic movie neighbourhood chunks.

    Args:
        candidates: Retrieval passages, including ``Movie:`` neighbourhood text.

    Returns:
        De-duplicated source cards ordered by appearance.
    """
    sources: list[SourceArtifact] = []
    seen: set[str] = set()
    for chunk in candidates:
        match = _MOVIE_LINE.search(chunk)
        if not match:
            continue
        title = match.group(1).strip()
        key = title.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        year = match.group(2)
        tagline_match = re.search(r'tagline:\s*"([^"]+)"', chunk)
        sources.append(
            SourceArtifact(
                id=_movie_id(title),
                title=title,
                subtitle=tagline_match.group(1) if tagline_match else None,
                year=year,
                poster_url=poster_url_for_title(title),
                tags=_parse_tags(chunk),
            )
        )
    return sources


_GRAPH_QUERY = """
UNWIND $titles AS title
MATCH (m:Movie)
WHERE m.title = title
OPTIONAL MATCH (p:Person)-[r]->(m)
WHERE type(r) IN ['ACTED_IN', 'DIRECTED', 'PRODUCED', 'WROTE', 'REVIEWED']
RETURN m.title AS movie_title,
       m.released AS movie_year,
       p.name AS person_name,
       type(r) AS rel_type
"""

_FULL_GRAPH_RELATIONSHIPS = [
    "ACTED_IN",
    "DIRECTED",
    "PRODUCED",
    "WROTE",
    "REVIEWED",
    "FOLLOWS",
]

_FULL_GRAPH_NODES_QUERY = """
MATCH (n)
WHERE n:Movie OR n:Person
RETURN labels(n) AS labels,
       n.title AS title,
       n.name AS name
"""

_FULL_GRAPH_LINKS_QUERY = """
MATCH (source)-[rel]->(target)
WHERE (source:Movie OR source:Person)
  AND (target:Movie OR target:Person)
  AND type(rel) IN $relationship_types
RETURN labels(source) AS source_labels,
       source.title AS source_title,
       source.name AS source_name,
       labels(target) AS target_labels,
       target.title AS target_title,
       target.name AS target_name,
       type(rel) AS rel_type
"""


def _node_artifact(labels: list[str], title: object, name: object) -> GraphNodeArtifact | None:
    """Build a graph node artifact from a Neo4j node row.

    Args:
        labels: Neo4j labels attached to the node.
        title: Movie title value when present.
        name: Person name value when present.

    Returns:
        A normalized graph node artifact, or ``None`` when the row lacks a
        supported Movie/Person label and display value.
    """
    if "Movie" in labels:
        label = str(title or "").strip()
        if not label:
            return None
        return GraphNodeArtifact(id=_movie_id(label), label=label, type="Movie")
    if "Person" in labels:
        label = str(name or "").strip()
        if not label:
            return None
        return GraphNodeArtifact(id=_person_id(label), label=label, type="Person")
    return None


def graph_from_titles(titles: list[str]) -> GraphArtifact:
    """Load a read-only person–movie subgraph for the given titles.

    Args:
        titles: Movie titles to expand in Neo4j.

    Returns:
        Nodes and links suitable for the graph panel. Returns an empty graph
        when Neo4j is unavailable or no rows match.
    """
    empty: GraphArtifact = {"nodes": [], "links": []}
    if not titles:
        return empty

    settings = get_settings()
    driver = get_neo4j_driver()
    nodes: dict[str, GraphNodeArtifact] = {}
    links: list[GraphLinkArtifact] = []
    link_keys: set[str] = set()

    def _read(tx: neo4j.ManagedTransaction) -> list[dict[str, Any]]:
        """Run the neighbourhood query inside a read transaction."""
        result = tx.run(_GRAPH_QUERY, titles=titles[:_MAX_GRAPH_MOVIES])
        return [dict(record) for record in result]

    try:
        with driver.session(database=settings.neo4j_database) as session:
            rows = session.execute_read(_read)
    except Exception:
        return empty

    for row in rows:
        movie_title = str(row.get("movie_title") or "").strip()
        if not movie_title:
            continue
        movie_node_id = _movie_id(movie_title)
        if movie_node_id not in nodes:
            nodes[movie_node_id] = GraphNodeArtifact(
                id=movie_node_id,
                label=movie_title,
                type="Movie",
            )
        person_name = str(row.get("person_name") or "").strip()
        rel_type = str(row.get("rel_type") or "").strip()
        if not person_name or not rel_type:
            continue
        person_node_id = _person_id(person_name)
        if person_node_id not in nodes:
            nodes[person_node_id] = GraphNodeArtifact(
                id=person_node_id,
                label=person_name,
                type="Person",
            )
        link_key = f"{person_node_id}->{movie_node_id}:{rel_type}"
        if link_key in link_keys:
            continue
        link_keys.add(link_key)
        links.append(
            GraphLinkArtifact(
                source=person_node_id,
                target=movie_node_id,
                label=rel_type.replace("_", " ").title(),
            )
        )

    return GraphArtifact(nodes=list(nodes.values()), links=links)


@lru_cache(maxsize=1)
def full_graph() -> GraphArtifact:
    """Load the complete read-only Movie/Person knowledge graph.

    Args:
        None.

    Returns:
        Every supported Movie/Person node and relationship in Neo4j, normalized
        with the same node ids as turn-level graph artifacts. Returns an empty
        graph if Neo4j is unavailable.
    """
    empty: GraphArtifact = {"nodes": [], "links": []}
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

    try:
        with driver.session(database=settings.neo4j_database) as session:
            node_rows, link_rows = session.execute_read(_read)
    except Exception:
        return empty

    for row in node_rows:
        node = _node_artifact(
            list(row.get("labels") or []),
            row.get("title"),
            row.get("name"),
        )
        if node is not None:
            nodes[node["id"]] = node

    for row in link_rows:
        source = _node_artifact(
            list(row.get("source_labels") or []),
            row.get("source_title"),
            row.get("source_name"),
        )
        target = _node_artifact(
            list(row.get("target_labels") or []),
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


def build_retrieval_artifacts(candidates: list[str]) -> RetrievalArtifacts:
    """Derive frontend sources and graph data from retrieval candidates.

    Args:
        candidates: Final reranked retrieval passages for the current turn.

    Returns:
        Structured sources and graph neighbourhood for the right pane.
    """
    sources = sources_from_candidates(candidates)
    titles = extract_movie_titles(candidates)
    if not titles and sources:
        titles = [cast(str, source["title"]) for source in sources]
    graph = graph_from_titles(titles)
    return RetrievalArtifacts(sources=sources, graph=graph)


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
    return GraphArtifact(
        nodes=[node for node in graph["nodes"] if node["id"] in kept_node_ids],
        links=[link for link in graph["links"] if link["target"] in cited_movie_ids],
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
