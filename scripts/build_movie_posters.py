"""Build a static movie poster URL map via the Wikipedia page summary API."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Titles in the bundled Neo4j seed, with Wikipedia page names when they differ.
_MOVIES: dict[str, str] = {
    "The Matrix": "The Matrix",
    "The Matrix Reloaded": "The Matrix Reloaded",
    "The Matrix Revolutions": "The Matrix Revolutions",
    "The Devil's Advocate": "The Devil's Advocate (1997 film)",
    "A Few Good Men": "A Few Good Men",
    "Top Gun": "Top Gun",
    "Jerry Maguire": "Jerry Maguire",
    "Stand By Me": "Stand by Me (film)",
    "As Good as It Gets": "As Good as It Gets",
    "What Dreams May Come": "What Dreams May Come (film)",
    "Snow Falling on Cedars": "Snow Falling on Cedars (film)",
    "You've Got Mail": "You've Got Mail",
    "Sleepless in Seattle": "Sleepless in Seattle",
    "Joe Versus the Volcano": "Joe Versus the Volcano",
    "When Harry Met Sally": "When Harry Met Sally",
    "That Thing You Do": "That Thing You Do!",
    "The Replacements": "The Replacements (2000 film)",
    "Rescue Dawn": "Rescue Dawn",
    "The Birdcage": "The Birdcage",
    "Unforgiven": "Unforgiven",
    "Johnny Mnemonic": "Johnny Mnemonic (film)",
    "Cloud Atlas": "Cloud Atlas (film)",
    "The Da Vinci Code": "The Da Vinci Code (film)",
    "V for Vendetta": "V for Vendetta (film)",
    "Speed Racer": "Speed Racer (film)",
    "Ninja Assassin": "Ninja Assassin",
    "The Green Mile": "The Green Mile (film)",
    "Frost/Nixon": "Frost/Nixon (film)",
    "Hoffa": "Hoffa (film)",
    "Apollo 13": "Apollo 13 (film)",
    "Twister": "Twister (1996 film)",
    "Cast Away": "Cast Away",
    "One Flew Over the Cuckoo's Nest": "One Flew Over the Cuckoo's Nest (film)",
    "Something's Gotta Give": "Something's Gotta Give (film)",
    "Bicentennial Man": "Bicentennial Man (film)",
    "Charlie Wilson's War": "Charlie Wilson's War (film)",
    "The Polar Express": "The Polar Express (film)",
    "A League of Their Own": "A League of Their Own",
}

_OUT = Path(__file__).resolve().parents[1] / "apps/agents/src/agents/data/movie_posters.json"


def _wiki_poster_url(page_title: str) -> str | None:
    """Return the Wikipedia thumbnail URL for a film page, if present."""
    encoded = urllib.parse.quote(page_title.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": "ReelDemo/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    thumb = data.get("thumbnail") or {}
    source = thumb.get("source")
    if not isinstance(source, str) or not source:
        return None
    # Request a slightly larger poster than the default ~320px thumb.
    return re.sub(r"/\d+px-", "/480px-", source)


def main() -> None:
    """Fetch poster URLs and write the JSON map used by the agents package."""
    posters: dict[str, str] = {}
    if _OUT.exists():
        posters = json.loads(_OUT.read_text(encoding="utf-8"))
    for movie_title, wiki_title in _MOVIES.items():
        if movie_title in posters:
            continue
        try:
            poster = _wiki_poster_url(wiki_title)
        except Exception as exc:
            print(f"MISS {movie_title}: {exc}")
            continue
        if poster:
            posters[movie_title] = poster
            print(f"OK   {movie_title}")
        else:
            print(f"MISS {movie_title}: no thumbnail")
        time.sleep(1.0)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(posters, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(posters)} posters to {_OUT}")


if __name__ == "__main__":
    main()
