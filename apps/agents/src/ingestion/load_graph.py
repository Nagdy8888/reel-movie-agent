"""Load the sample movies dataset and constraints into Neo4j."""

from pathlib import Path
from typing import LiteralString, cast

from agents.clients import get_neo4j_driver
from agents.settings import get_settings

CONSTRAINTS: list[LiteralString] = [
    "CREATE CONSTRAINT movie_title IF NOT EXISTS FOR (m:Movie) REQUIRE m.title IS UNIQUE",
    "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE",
]


def _read_seed() -> str:
    """Read the bundled movies Cypher seed file."""
    seed = Path(__file__).resolve().parents[2] / "data" / "movies.cypher"
    return seed.read_text(encoding="utf-8")


def _split_statements(cypher: str) -> list[str]:
    """Split a multi-statement Cypher script into runnable statements.

    The Neo4j Bolt driver executes one statement per ``session.run``; the
    bundled movies seed is a semicolon-separated script.
    """
    statements: list[str] = []
    for raw in cypher.split(";"):
        stmt = raw.strip()
        if not stmt or stmt.startswith("//"):
            continue
        statements.append(stmt)
    return statements


def load_movies() -> None:
    """Load constraints and the sample movies dataset into Neo4j.

    Side effects: writes nodes/relationships to Neo4j. Idempotent for
    constraints; the seed uses MERGE/CREATE per the chosen dataset.
    """
    settings = get_settings()
    driver = get_neo4j_driver()
    with driver.session(database=settings.neo4j_database) as session:
        for stmt in CONSTRAINTS:
            session.run(stmt)
        for stmt in _split_statements(_read_seed()):
            # Seed file contents are trusted project assets, not user input.
            session.run(cast(LiteralString, stmt))
    print("Loaded sample movies dataset.")


if __name__ == "__main__":
    load_movies()
