"""Build the packaged 5,000-movie graph bundle from Kaggle CSV exports."""

from __future__ import annotations

import argparse
import ast
import csv
import gzip
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

DEFAULT_LIMIT = 5_000
MAX_CAST = 12
MAX_KEYWORDS = 10
MAX_CREW_PER_ROLE = 5
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
AURA_FREE_NODE_LIMIT = 200_000
AURA_FREE_RELATIONSHIP_LIMIT = 400_000

WRITING_JOBS = frozenset(
    {
        "Adaptation",
        "Novel",
        "Original Story",
        "Screenplay",
        "Story",
        "Teleplay",
        "Writer",
    }
)
PRODUCING_JOBS = frozenset(
    {
        "Associate Producer",
        "Co-Producer",
        "Executive Producer",
        "Producer",
    }
)


def parse_structured(value: object) -> list[dict[str, Any]]:
    """Parse a Kaggle JSON/Python-literal list, returning safe dictionary rows.

    Args:
        value: Raw CSV field value.

    Returns:
        Parsed dictionary items, or an empty list for malformed input.
    """
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def parse_int(value: object) -> int | None:
    """Return a non-negative integer parsed from a CSV value.

    Args:
        value: Candidate numeric value.

    Returns:
        Parsed integer, or ``None`` when invalid.
    """
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def parse_float(value: object) -> float | None:
    """Return a finite float parsed from a CSV value.

    Args:
        value: Candidate numeric value.

    Returns:
        Parsed float, or ``None`` when invalid or non-finite.
    """
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def image_url(path: object) -> str | None:
    """Return a complete TMDB image URL for a relative image path.

    Args:
        path: Relative TMDB image path.

    Returns:
        Complete HTTPS URL, or ``None`` when unavailable.
    """
    if not isinstance(path, str) or not path.strip():
        return None
    clean_path = path.strip()
    if clean_path.startswith("https://"):
        return clean_path
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    return f"{TMDB_IMAGE_BASE}{clean_path}"


def _clean_text(value: object, *, max_length: int | None = None) -> str:
    """Normalize a text field and optionally limit its length."""
    text = " ".join(str(value or "").split())
    if max_length is not None:
        return text[:max_length].rstrip()
    return text


def _person(entry: Mapping[str, Any], *, include_character: bool = False) -> dict[str, Any] | None:
    """Normalize a cast or crew record with a stable TMDB identifier."""
    person_id = parse_int(entry.get("id"))
    name = _clean_text(entry.get("name"))
    if person_id is None or not name:
        return None
    person: dict[str, Any] = {
        "tmdbId": person_id,
        "name": name,
        "profileUrl": image_url(entry.get("profile_path")),
    }
    if include_character:
        person["character"] = _clean_text(entry.get("character"), max_length=200)
        person["order"] = parse_int(entry.get("order")) or 0
    return person


def classify_crew(entries: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Classify and cap directors, writers, and producers.

    Args:
        entries: Parsed crew records.

    Returns:
        Crew grouped as ``directors``, ``writers``, and ``producers``.
    """
    groups: dict[str, list[dict[str, Any]]] = {
        "directors": [],
        "writers": [],
        "producers": [],
    }
    seen: dict[str, set[int]] = {key: set() for key in groups}
    for entry in entries:
        job = _clean_text(entry.get("job"))
        group: str | None = None
        if job == "Director":
            group = "directors"
        elif job in WRITING_JOBS:
            group = "writers"
        elif job in PRODUCING_JOBS:
            group = "producers"
        if group is None or len(groups[group]) >= MAX_CREW_PER_ROLE:
            continue
        person = _person(entry)
        if person is None or person["tmdbId"] in seen[group]:
            continue
        person["job"] = job
        groups[group].append(person)
        seen[group].add(person["tmdbId"])
    return groups


def select_movies(rows: Iterable[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Select unique high-signal movies with deterministic tie-breaking.

    Args:
        rows: Raw movie metadata rows.
        limit: Maximum number of movies to select.

    Returns:
        Valid rows ordered by descending vote count then ascending TMDB ID.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        movie_id = parse_int(row.get("id"))
        title = _clean_text(row.get("title"))
        if movie_id is None or not title:
            continue
        normalized = dict(row)
        normalized["_tmdb_id"] = movie_id
        normalized["_vote_count"] = parse_int(row.get("vote_count")) or 0
        previous = by_id.get(movie_id)
        if previous is None or normalized["_vote_count"] > previous["_vote_count"]:
            by_id[movie_id] = normalized
    return sorted(
        by_id.values(),
        key=lambda item: (-int(item["_vote_count"]), int(item["_tmdb_id"])),
    )[:limit]


def _read_lookup(path: Path, payload_key: str) -> dict[int, list[dict[str, Any]]]:
    """Read a TMDB-ID keyed structured-list CSV."""
    lookup: dict[int, list[dict[str, Any]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            item_id = parse_int(row.get("id"))
            if item_id is not None:
                lookup[item_id] = parse_structured(row.get(payload_key))
    return lookup


def _dedupe_named(entries: Sequence[Mapping[str, Any]], limit: int) -> list[str]:
    """Return ordered, unique non-empty names from structured records."""
    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        name = _clean_text(entry.get("name"))
        key = name.casefold()
        if not name or key in seen:
            continue
        names.append(name)
        seen.add(key)
        if len(names) >= limit:
            break
    return names


def _normalize_cast(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize the first unique cast members in billing order."""
    ordered = sorted(entries, key=lambda entry: parse_int(entry.get("order")) or 0)
    cast: list[dict[str, Any]] = []
    seen: set[int] = set()
    for entry in ordered:
        person = _person(entry, include_character=True)
        if person is None or person["tmdbId"] in seen:
            continue
        cast.append(person)
        seen.add(person["tmdbId"])
        if len(cast) >= MAX_CAST:
            break
    return cast


def build_movie(
    row: Mapping[str, Any],
    credits: Mapping[str, Sequence[Mapping[str, Any]]],
    keywords: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one normalized movie record.

    Args:
        row: Selected movie metadata row.
        credits: Parsed ``cast`` and ``crew`` records.
        keywords: Parsed keyword records.

    Returns:
        JSON-serializable movie graph record.
    """
    release_date = _clean_text(row.get("release_date"))
    year = parse_int(release_date[:4]) if release_date else None
    crew = classify_crew(credits.get("crew", []))
    return {
        "tmdbId": int(row["_tmdb_id"]),
        "imdbId": _clean_text(row.get("imdb_id")) or None,
        "title": _clean_text(row.get("title")),
        "originalTitle": _clean_text(row.get("original_title")) or None,
        "year": year,
        "releaseDate": release_date or None,
        "overview": _clean_text(row.get("overview"), max_length=2_500) or None,
        "tagline": _clean_text(row.get("tagline"), max_length=500) or None,
        "posterUrl": image_url(row.get("poster_path")),
        "rating": parse_float(row.get("vote_average")),
        "voteCount": parse_int(row.get("vote_count")) or 0,
        "popularity": parse_float(row.get("popularity")),
        "runtime": parse_float(row.get("runtime")),
        "genres": _dedupe_named(parse_structured(row.get("genres")), limit=20),
        "keywords": _dedupe_named(keywords, limit=MAX_KEYWORDS),
        "cast": _normalize_cast(credits.get("cast", [])),
        **crew,
    }


def calculate_manifest(movies: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate unique node and per-type relationship counts.

    Args:
        movies: Normalized movie records.

    Returns:
        Manifest with count totals and Aura Free capacity status.
    """
    people: set[int] = set()
    genres: set[str] = set()
    keywords: set[str] = set()
    relationship_counts = {
        "ACTED_IN": 0,
        "DIRECTED": 0,
        "WROTE": 0,
        "PRODUCED": 0,
        "IN_GENRE": 0,
        "HAS_KEYWORD": 0,
    }
    for movie in movies:
        for field, relationship in (
            ("cast", "ACTED_IN"),
            ("directors", "DIRECTED"),
            ("writers", "WROTE"),
            ("producers", "PRODUCED"),
        ):
            members = movie.get(field, [])
            if isinstance(members, list):
                people.update(
                    int(member["tmdbId"])
                    for member in members
                    if isinstance(member, dict) and parse_int(member.get("tmdbId")) is not None
                )
                relationship_counts[relationship] += len(members)
        movie_genres = movie.get("genres", [])
        movie_keywords = movie.get("keywords", [])
        if isinstance(movie_genres, list):
            genres.update(str(name) for name in movie_genres)
            relationship_counts["IN_GENRE"] += len(movie_genres)
        if isinstance(movie_keywords, list):
            keywords.update(str(name) for name in movie_keywords)
            relationship_counts["HAS_KEYWORD"] += len(movie_keywords)
    node_counts = {
        "Movie": len(movies),
        "Person": len(people),
        "Genre": len(genres),
        "Keyword": len(keywords),
    }
    total_nodes = sum(node_counts.values())
    total_relationships = sum(relationship_counts.values())
    return {
        "nodeCounts": node_counts,
        "relationshipCounts": relationship_counts,
        "totalNodes": total_nodes,
        "totalRelationships": total_relationships,
        "limits": {
            "maxNodes": AURA_FREE_NODE_LIMIT,
            "maxRelationships": AURA_FREE_RELATIONSHIP_LIMIT,
            "withinAuraFree": (
                total_nodes <= AURA_FREE_NODE_LIMIT
                and total_relationships <= AURA_FREE_RELATIONSHIP_LIMIT
            ),
        },
    }


def build_bundle(dataset_dir: Path, limit: int) -> dict[str, Any]:
    """Read Kaggle exports and return the normalized graph bundle.

    Args:
        dataset_dir: Directory containing metadata, credits, and keywords CSVs.
        limit: Number of high-signal movies to include.

    Returns:
        Bundle containing a manifest and normalized movies.

    Raises:
        FileNotFoundError: If a required CSV does not exist.
        ValueError: If fewer valid movies than requested can be produced.
    """
    metadata_path = dataset_dir / "movies_metadata.csv"
    credits_path = dataset_dir / "credits.csv"
    keywords_path = dataset_dir / "keywords.csv"
    for path in (metadata_path, credits_path, keywords_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required Kaggle file not found: {path}")

    with metadata_path.open(encoding="utf-8-sig", newline="") as handle:
        selected = select_movies(csv.DictReader(handle), limit)
    if len(selected) != limit:
        raise ValueError(f"Expected {limit} valid movies, found {len(selected)}")

    credits_by_id: dict[int, dict[str, list[dict[str, Any]]]] = {}
    with credits_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            item_id = parse_int(row.get("id"))
            if item_id is not None:
                credits_by_id[item_id] = {
                    "cast": parse_structured(row.get("cast")),
                    "crew": parse_structured(row.get("crew")),
                }
    keywords_by_id = _read_lookup(keywords_path, "keywords")
    movies = [
        build_movie(
            row,
            credits_by_id.get(int(row["_tmdb_id"]), {"cast": [], "crew": []}),
            keywords_by_id.get(int(row["_tmdb_id"]), []),
        )
        for row in selected
    ]
    return {
        "schemaVersion": 1,
        "selection": {
            "limit": limit,
            "order": "vote_count_desc_tmdb_id_asc",
            "maxCast": MAX_CAST,
            "maxKeywords": MAX_KEYWORDS,
            "maxCrewPerRole": MAX_CREW_PER_ROLE,
        },
        "manifest": calculate_manifest(movies),
        "movies": movies,
    }


def write_bundle(bundle: Mapping[str, Any], output: Path) -> None:
    """Write a deterministic gzip-compressed JSON graph bundle.

    Args:
        bundle: Bundle returned by :func:`build_bundle`.
        output: Destination ``.json.gz`` path.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            compressed.write(payload.encode("utf-8"))


def _parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", type=Path, help="Directory containing Kaggle CSV exports.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/agents/src/agents/data/movies_subset.json.gz"),
    )
    return parser


def main() -> None:
    """Build the graph bundle and print its capacity manifest."""
    args = _parser().parse_args()
    bundle = build_bundle(args.dataset_dir, args.limit)
    write_bundle(bundle, args.output)
    print(json.dumps(bundle["manifest"], indent=2, sort_keys=True))
    if not bundle["manifest"]["limits"]["withinAuraFree"]:
        raise SystemExit("Generated graph exceeds Aura Free capacity limits.")
    print(f"Wrote {len(bundle['movies'])} movies to {args.output}")


if __name__ == "__main__":
    main()
