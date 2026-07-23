"""Structured sources and graph payloads derived from retrieval candidates."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal, TypedDict, cast

from agents.projection import (
    fetch_full_projection,
    fetch_movie_neighbourhood,
    fetch_movies_by_ids,
    find_movies_mentioned_in_text,
    movie_id_from_wikipedia,
)

_MOVIE_KEY = re.compile(r"movie:(\d+)")
_MOVIE_LINE = re.compile(
    r"^Movie:\s+(.+?)(?:\s+\((\d{4})\))?\s+\[movie:(\d+)\]",
    re.MULTILINE,
)
_CAST_LINE = re.compile(r"Cast:\s*(.+?)(?:\n|$)", re.I)
_POSTER_LINE = re.compile(r"Poster URL:\s*(https://\S+)", re.I)

_MAX_GRAPH_MOVIES = 40
_MAX_SOURCE_TAGS = 2
# Soft cap when the question does not name a recovered title (recommendations).
_MAX_UNANCHORED_MOVIES = 5


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


def extract_movie_keys(candidates: list[str]) -> list[str]:
    """Collect unique ``movie:{wikipedia_id}`` keys from retrieval text.

    Prefers explicit ``movie:N`` tokens (LightRAG file_path / formatted context).
    Falls back to case-insensitive title matches against the projection.

    Args:
        candidates: Raw retrieval passages.

    Returns:
        De-duplicated movie keys in first-seen order.
    """
    keys: list[str] = []
    seen: set[str] = set()
    blob = "\n".join(candidates)

    for match in _MOVIE_KEY.finditer(blob):
        key = movie_id_from_wikipedia(match.group(1))
        if key not in seen:
            seen.add(key)
            keys.append(key)

    if keys:
        return keys[:_MAX_GRAPH_MOVIES]

    try:
        movies = find_movies_mentioned_in_text(blob)
    except Exception:
        return []
    for movie in movies:
        if title_mentioned_in_text(movie["title"], blob) and movie["id"] not in seen:
            seen.add(movie["id"])
            keys.append(movie["id"])
            if len(keys) >= _MAX_GRAPH_MOVIES:
                break
    return keys


def extract_movie_ids(candidates: list[str]) -> list[int]:
    """Collect unique Wikipedia movie IDs referenced in retrieval candidates.

    Args:
        candidates: Raw retrieval passages.

    Returns:
        De-duplicated Wikipedia IDs in first-seen order.
    """
    ids: list[int] = []
    for key in extract_movie_keys(candidates):
        suffix = key.removeprefix("movie:")
        if suffix.isdigit():
            ids.append(int(suffix))
    return ids


def extract_movie_titles(candidates: list[str]) -> list[str]:
    """Collect unique movie titles referenced in retrieval candidate text.

    Args:
        candidates: Raw retrieval passages.

    Returns:
        De-duplicated movie titles in first-seen order.
    """
    titles: list[str] = []
    seen: set[str] = set()
    for chunk in candidates:
        for match in _MOVIE_LINE.finditer(chunk):
            title = match.group(1).strip()
            key = title.casefold()
            if key and key not in seen:
                seen.add(key)
                titles.append(title)
    if titles:
        return titles
    # Title fallback via projection hydration of recovered keys.
    try:
        movies = fetch_movies_by_ids(extract_movie_keys(candidates))
    except Exception:
        return titles
    for movie in movies:
        key = movie["title"].casefold()
        if key not in seen:
            seen.add(key)
            titles.append(movie["title"])
    return titles


def sources_from_candidates(candidates: list[str]) -> list[SourceArtifact]:
    """Build source cards from context that already contains movie keys.

    Args:
        candidates: Retrieval passages, including formatted movie blocks.

    Returns:
        De-duplicated source cards ordered by appearance.
    """
    keys = extract_movie_keys(candidates)
    if not keys:
        return []
    try:
        return artifacts_from_movie_keys(keys)["sources"]
    except Exception:
        # Last-resort parse of formatted Movie: lines without a DB round-trip.
        sources: list[SourceArtifact] = []
        seen: set[str] = set()
        for chunk in candidates:
            match = _MOVIE_LINE.search(chunk)
            if not match:
                continue
            movie_key = movie_id_from_wikipedia(match.group(3))
            if movie_key in seen:
                continue
            seen.add(movie_key)
            cast_match = _CAST_LINE.search(chunk)
            tags: list[str] = []
            if cast_match:
                tags = [
                    name.split(" as ")[0].strip()
                    for name in cast_match.group(1).split(";")
                    if name.strip()
                ][:_MAX_SOURCE_TAGS]
            poster_match = _POSTER_LINE.search(chunk)
            sources.append(
                SourceArtifact(
                    id=movie_key,
                    title=match.group(1).strip(),
                    subtitle=None,
                    year=match.group(2),
                    poster_url=poster_match.group(1) if poster_match else None,
                    tags=tags,
                )
            )
        return sources


def artifacts_from_movie_ids(movie_ids: list[int]) -> RetrievalArtifacts:
    """Load source cards and graph neighborhoods for Wikipedia movie IDs.

    Args:
        movie_ids: Wikipedia movie IDs to hydrate.

    Returns:
        Source cards and focused subgraph for the answer view.
    """
    return artifacts_from_movie_keys([movie_id_from_wikipedia(mid) for mid in movie_ids])


def artifacts_from_movie_keys(movie_keys: list[str]) -> RetrievalArtifacts:
    """Load source cards and graph neighborhoods for projection movie keys.

    Args:
        movie_keys: ``movie:{wikipedia_id}`` keys.

    Returns:
        Source cards and graph data. Both are empty when the projection is
        unavailable or no rows match.
    """
    empty: GraphArtifact = {"nodes": [], "links": []}
    if not movie_keys:
        return RetrievalArtifacts(sources=[], graph=empty)

    bounded = movie_keys[:_MAX_GRAPH_MOVIES]
    try:
        movies, people, genres, acted_in, in_genre = fetch_movie_neighbourhood(bounded)
    except Exception:
        return RetrievalArtifacts(sources=[], graph=empty)

    sources: list[SourceArtifact] = []
    nodes: dict[str, GraphNodeArtifact] = {}
    links: list[GraphLinkArtifact] = []
    link_keys: set[str] = set()
    person_names = {person["id"]: person["name"] for person in people}
    cast_map: dict[str, list[str]] = {movie["id"]: [] for movie in movies}
    for edge in sorted(
        acted_in,
        key=lambda item: (
            item["movie_id"],
            item["billing_order"] if item["billing_order"] is not None else 2**31,
            item["person_id"],
        ),
    ):
        names = cast_map.setdefault(edge["movie_id"], [])
        name = person_names.get(edge["person_id"])
        if name and name not in names and len(names) < _MAX_SOURCE_TAGS:
            names.append(name)

    for movie in movies:
        year = movie.get("year")
        sources.append(
            SourceArtifact(
                id=movie["id"],
                title=movie["title"],
                subtitle=movie.get("subtitle"),
                year=str(year) if isinstance(year, int) else None,
                poster_url=movie.get("poster_url"),
                tags=cast_map.get(movie["id"], [])[:_MAX_SOURCE_TAGS],
            )
        )
        nodes[movie["id"]] = GraphNodeArtifact(id=movie["id"], label=movie["title"], type="Movie")

    for person in people:
        nodes[person["id"]] = GraphNodeArtifact(
            id=person["id"], label=person["name"], type="Person"
        )
    for genre in genres:
        nodes[genre["id"]] = GraphNodeArtifact(id=genre["id"], label=genre["name"], type="Genre")

    for edge in acted_in:
        link_key = f"{edge['person_id']}->{edge['movie_id']}:ACTED_IN"
        if link_key in link_keys:
            continue
        link_keys.add(link_key)
        links.append(
            GraphLinkArtifact(
                source=edge["person_id"],
                target=edge["movie_id"],
                label="Acted In",
            )
        )
    for edge in in_genre:
        link_key = f"{edge['movie_id']}->{edge['genre_id']}:IN_GENRE"
        if link_key in link_keys:
            continue
        link_keys.add(link_key)
        links.append(
            GraphLinkArtifact(
                source=edge["movie_id"],
                target=edge["genre_id"],
                label="In Genre",
            )
        )

    return RetrievalArtifacts(
        sources=sources,
        graph=GraphArtifact(nodes=list(nodes.values()), links=links),
    )


@lru_cache(maxsize=1)
def _full_graph_cached() -> GraphArtifact:
    """Load and cache a successful full-graph snapshot from the projection.

    Raises:
        Exception: Propagates DB failures so callers avoid caching empties.
    """
    movies, people, genres, acted_in, in_genre = fetch_full_projection()
    nodes: dict[str, GraphNodeArtifact] = {}
    links: list[GraphLinkArtifact] = []
    link_keys: set[str] = set()

    for movie in movies:
        nodes[movie["id"]] = GraphNodeArtifact(id=movie["id"], label=movie["title"], type="Movie")
    for person in people:
        nodes[person["id"]] = GraphNodeArtifact(
            id=person["id"], label=person["name"], type="Person"
        )
    for genre in genres:
        nodes[genre["id"]] = GraphNodeArtifact(id=genre["id"], label=genre["name"], type="Genre")

    for edge in acted_in:
        if edge["person_id"] not in nodes or edge["movie_id"] not in nodes:
            continue
        link_key = f"{edge['person_id']}->{edge['movie_id']}:ACTED_IN"
        if link_key in link_keys:
            continue
        link_keys.add(link_key)
        links.append(
            GraphLinkArtifact(
                source=edge["person_id"],
                target=edge["movie_id"],
                label="Acted In",
            )
        )
    for edge in in_genre:
        if edge["movie_id"] not in nodes or edge["genre_id"] not in nodes:
            continue
        link_key = f"{edge['movie_id']}->{edge['genre_id']}:IN_GENRE"
        if link_key in link_keys:
            continue
        link_keys.add(link_key)
        links.append(
            GraphLinkArtifact(
                source=edge["movie_id"],
                target=edge["genre_id"],
                label="In Genre",
            )
        )

    return GraphArtifact(nodes=list(nodes.values()), links=links)


def full_graph() -> GraphArtifact:
    """Load the complete Movie/Person/Genre projection graph.

    Returns:
        Every Movie, Person, and Genre node plus Acted In / In Genre links.
        Returns an empty graph if the projection is unavailable. Failures and
        empty snapshots are not cached.
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


def title_mentioned_in_text(title: str, text: str) -> bool:
    """Return True when ``title`` appears as a whole phrase in ``text``.

    Args:
        title: Movie title from the projection.
        text: User question or assistant answer.

    Returns:
        Whether the title matches with word-boundary semantics.
    """
    cleaned = title.strip()
    if not cleaned or not text:
        return False
    return (
        re.search(
            rf"(?<!\w){re.escape(cleaned)}(?!\w)",
            text,
            flags=re.IGNORECASE,
        )
        is not None
    )


def prioritize_movie_keys_for_question(
    question: str,
    movie_keys: list[str],
) -> list[str]:
    """Keep movies named in the question; otherwise soft-cap incidental hits.

    Hybrid LightRAG context often embeds several ``movie:N`` keys. For a
    question like "Who starred in The Hunger Games?", only that title should
    drive the sources pane and answer neighbourhood.

    Args:
        question: The user's latest message.
        movie_keys: Recovered projection keys in first-seen order.

    Returns:
        Filtered keys to hydrate into sources/graph.
    """
    if not movie_keys:
        return []
    if not question.strip():
        return movie_keys[:_MAX_UNANCHORED_MOVIES]
    try:
        movies = fetch_movies_by_ids(movie_keys)
    except Exception:
        return movie_keys[:_MAX_UNANCHORED_MOVIES]
    by_id = {movie["id"]: movie for movie in movies}
    matched: list[str] = []
    for key in movie_keys:
        movie = by_id.get(key)
        if movie and title_mentioned_in_text(movie["title"], question):
            matched.append(key)
    if matched:
        return matched[:_MAX_GRAPH_MOVIES]
    return movie_keys[:_MAX_UNANCHORED_MOVIES]


def build_retrieval_artifacts(
    candidates: list[str],
    *,
    question: str = "",
) -> RetrievalArtifacts:
    """Derive frontend sources and graph data from retrieval candidates.

    Args:
        candidates: Final reranked retrieval passages for the current turn.
        question: User question used to drop incidental recovered movies.

    Returns:
        Structured sources and graph neighbourhood for the right pane.
    """
    keys = prioritize_movie_keys_for_question(question, extract_movie_keys(candidates))
    empty: GraphArtifact = {"nodes": [], "links": []}
    try:
        artifacts = artifacts_from_movie_keys(keys)
    except Exception:
        artifacts = RetrievalArtifacts(sources=[], graph=empty)
    sources = artifacts["sources"]
    if not sources:
        sources = sources_from_candidates(candidates)
        if question.strip() and sources:
            allowed = {
                source["id"]
                for source in sources
                if title_mentioned_in_text(source["title"], question)
            }
            if allowed:
                sources = [source for source in sources if source["id"] in allowed]
                artifacts = artifacts_from_movie_keys([s["id"] for s in sources])
                return RetrievalArtifacts(
                    sources=artifacts["sources"] or sources,
                    graph=artifacts["graph"],
                )
            sources = sources[:_MAX_UNANCHORED_MOVIES]
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
        A subgraph containing cited movies and their connected people/genres.
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
    *,
    question: str = "",
) -> RetrievalArtifacts:
    """Align the right pane with movies cited in the answer or question.

    Args:
        sources: Source cards built from retrieval candidates.
        graph: Subgraph built from retrieval candidates.
        answer: The assistant's final grounded reply for the turn.
        question: Optional user question. Used when the answer lists cast/facts
            without repeating the movie title (common for "who starred in …").

    Returns:
        Filtered sources and graph. When neither answer nor question names a
        recovered title, the original artifacts are returned unchanged.
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
    if not cited and question.strip():
        cited = [title for title in available if title_mentioned_in_text(title, question)]
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
