# Phase 3 — Neo4j (Docker) + Movie Data Ingestion + Vector Index

## Objective

Stand up **Neo4j in Docker**, load the **sample movies dataset**, and build a **vector index** over movie plot/tagline embeddings so the agent (Phase 4) can do both structured (Cypher) and semantic (vector) retrieval. Also document how to create a **read-only** access path for the agent.

At the end you can open Neo4j Browser, see `Movie`/`Person`/`Genre` nodes, and a vector index exists.

## Prerequisites

- Phase 2 complete.
- `.env` has `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENAI_API_KEY`, `OPENAI_EMBED_MODEL`.

## Steps

### 1. Add Neo4j to `docker-compose.yml`

Add a `neo4j` service (keep the existing `agent` service):

```yaml
services:
  neo4j:
    image: neo4j:5.24
    environment:
      NEO4J_AUTH: "neo4j/${NEO4J_PASSWORD}"
      NEO4J_PLUGINS: '["apoc"]'
    ports:
      - "7474:7474"   # Browser (HTTP)
      - "7687:7687"   # Bolt
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10

  # ... existing `agent` service ...

volumes:
  neo4j_data:
```

Start it and wait until healthy:

```powershell
docker compose up -d neo4j
```

Open `http://localhost:7474`, log in with `neo4j` / your `NEO4J_PASSWORD`, confirm access.

### 2. Get the sample movies Cypher — `apps/agents/data/movies.cypher`

Obtain the Neo4j sample movies dataset as a Cypher seed file and save it to `apps/agents/data/movies.cypher`. Options (pick one, verify it loads):
- The script shown by running `:play movies` in Neo4j Browser (the classic `Movie`/`Person` graph with `ACTED_IN`/`DIRECTED`).
- The `movies.cypher` from the public `neo4j-graph-examples/movies` repository.

The dataset must produce at least: `(:Movie {title, released, tagline})`, `(:Person {name, born})`, and relationships `(:Person)-[:ACTED_IN]->(:Movie)` and `(:Person)-[:DIRECTED]->(:Movie)`. If the chosen dataset lacks `Genre`, that is acceptable for the demo — adjust Phase 4 examples accordingly.

> If you cannot fetch a file, you may inline a compact `CREATE` script covering ~30 movies. Keep it in `data/movies.cypher` either way so ingestion is reproducible.

### 3. Neo4j driver factory — extend `apps/agents/src/agents/clients.py`

Add a pooled driver factory (append to the existing file):

```python
from functools import lru_cache

import neo4j

from agents.settings import get_settings


@lru_cache(maxsize=1)
def get_neo4j_driver() -> neo4j.Driver:
    """Return the shared, pooled Neo4j driver.

    Cached so a single connection pool is reused across the process. Callers
    must NOT close it per request; it is closed on process shutdown.
    """
    settings = get_settings()
    return neo4j.GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
```

Add the Neo4j + embedding fields to `AgentSettings` in `settings.py`:

```python
    neo4j_uri: str = Field(description="Neo4j Bolt URI.")
    neo4j_username: str = Field(default="neo4j", description="Neo4j username.")
    neo4j_password: str = Field(description="Neo4j password.")
    neo4j_database: str = Field(default="neo4j", description="Neo4j database name.")
    openai_embed_model: str = Field(
        default="text-embedding-3-large", description="OpenAI embedding model."
    )
    vector_index_name: str = Field(
        default="movie_plot_embeddings", description="Neo4j vector index name."
    )
    embedding_dimensions: int = Field(
        default=3072, description="Embedding vector size (text-embedding-3-large=3072)."
    )
```

### 4. Load script — `apps/agents/src/ingestion/load_graph.py`

```python
"""Load the sample movies dataset and constraints into Neo4j."""

from pathlib import Path

from agents.clients import get_neo4j_driver
from agents.settings import get_settings

CONSTRAINTS = [
    "CREATE CONSTRAINT movie_title IF NOT EXISTS FOR (m:Movie) REQUIRE m.title IS UNIQUE",
    "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE",
]


def _read_seed() -> str:
    """Read the bundled movies Cypher seed file."""
    seed = Path(__file__).resolve().parents[2] / "data" / "movies.cypher"
    return seed.read_text(encoding="utf-8")


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
        session.run(_read_seed())
    print("Loaded sample movies dataset.")


if __name__ == "__main__":
    load_movies()
```

### 5. Vector index + embeddings — `apps/agents/src/ingestion/build_index.py`

```python
"""Generate plot/tagline embeddings and build the Neo4j vector index."""

from neo4j_graphrag.embeddings import OpenAIEmbeddings
from neo4j_graphrag.indexes import create_vector_index

from agents.clients import get_neo4j_driver
from agents.settings import get_settings


def build_vector_index() -> None:
    """Embed movie plot/tagline text and create a Neo4j vector index.

    Side effects: writes an `embedding` property on Movie nodes and creates a
    vector index. Safe to re-run (index creation is IF NOT EXISTS).
    """
    settings = get_settings()
    driver = get_neo4j_driver()
    embedder = OpenAIEmbeddings(model=settings.openai_embed_model)

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
```

> If the chosen dataset has richer plot text, embed that instead of `tagline`. Keep the `embedding` property name consistent with the index.

### 6. Run ingestion

```powershell
uv run python -m ingestion.load_graph
uv run python -m ingestion.build_index
```

(Run from repo root; `-m` works because `ingestion` is an installed package. If module resolution fails, run from `apps/agents` with the same commands.)

### 7. Read-only access for the agent (document + apply where supported)

The agent must query Neo4j **read-only**. Two layers:
1. **Application layer (always):** the agent will run generated Cypher via `session.execute_read(...)` and reject write clauses with a regex guard (implemented in Phase 4). This works on every Neo4j edition.
2. **Database layer (if supported):** on Neo4j **Enterprise / Aura Professional**, create a dedicated read-only user/role and point the agent's driver at it. On **Community / Aura Free** (no RBAC), rely on layer 1 only.

Document the exact steps for the read-only role in `docs/setup/neo4j.md` (created in Phase 10). For now, note in a comment which `NEO4J_USERNAME` the agent uses.

## Environment variables

`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENAI_API_KEY`, `OPENAI_EMBED_MODEL`.

## Acceptance criteria

- [ ] `docker compose up -d neo4j` runs and the container becomes healthy.
- [ ] After `load_graph`, Neo4j Browser shows `Movie` and `Person` nodes with relationships (`MATCH (m:Movie) RETURN count(m)` > 0).
- [ ] After `build_index`, `SHOW VECTOR INDEXES` lists `movie_plot_embeddings`, and Movie nodes have an `embedding` property.
- [ ] `uv run ruff check .` passes; all new functions have docstrings.

## Do NOT

- Do NOT embed inside the agent request path — embeddings are precomputed here.
- Do NOT give the agent write access at the app layer.
- Do NOT create one driver per query — use the cached `get_neo4j_driver()`.

## Relevant rules & skills

- Rules: `python-standards` (pooled clients), `security` (read-only intent), `documentation`.
- Skill: `verify-standards`.
