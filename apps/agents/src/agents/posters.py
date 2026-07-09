"""Static movie poster URLs for the bundled Neo4j seed dataset."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data" / "movie_posters.json"


@lru_cache(maxsize=1)
def _poster_map() -> dict[str, str]:
    """Load the title -> poster URL map shipped with the agents package."""
    if not _DATA.exists():
        return {}
    return json.loads(_DATA.read_text(encoding="utf-8"))


def poster_url_for_title(title: str) -> str | None:
    """Return a poster image URL for a known seed movie title.

    Args:
        title: Movie title as stored on ``Movie.title`` nodes.

    Returns:
        A poster URL, or ``None`` when the title is not in the curated map.
    """
    return _poster_map().get(title.strip())
