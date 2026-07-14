# Reel — GraphRAG Movie Assistant

Reel is a uv-workspace monorepo for a movie Q&A and recommendation assistant. Natural-language questions are grounded in a Neo4j knowledge graph via hybrid GraphRAG (Text2Cypher + vector/full-text retrieval with graph expansion), served through a FastAPI backend with Supabase JWT auth, and consumed by a Next.js chat UI.

## Monorepo layout

| Path | Role |
|------|------|
| `apps/agents` | LangGraph deployable — graph, nodes, tools, prompts, Neo4j ingestion |
| `apps/backend` | FastAPI HTTP layer — auth, chat SSE, chat history, readiness |
| `apps/frontend` | Next.js App Router UI (chat, sources, graph canvas) |
| `docs/` | Architecture notes, setup guides, reviews |
| `scripts/` | Dataset build helpers and smoke utilities |

**Placement rule:** graph/retrieval logic lives in `apps/agents`; HTTP transport lives in `apps/backend` (imports the compiled graph). No reverse imports.

## Prerequisites

- Python **3.11+** and [uv](https://docs.astral.sh/uv/)
- Node **20+** and [pnpm](https://pnpm.io/) (frontend)
- Docker (optional, for local Neo4j via `docker-compose`)
- Accounts / keys: OpenAI, Neo4j (local or Aura), Supabase project (auth + Postgres)

## Quick start (local)

### 1. Environment

```bash
cp .env.example .env
# Fill OPENAI_*, NEO4J_*, SUPABASE_*, CORS_ALLOW_ORIGINS, etc.
```

Frontend also needs `apps/frontend/.env.local` (not committed):

```bash
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 2. Install Python workspace

```bash
uv sync --group dev
```

### 3. Neo4j + movie graph

Start Neo4j (Compose or Aura), then load the packaged graph and build indexes. Order matters:

```bash
# Optional local Neo4j
docker compose up -d neo4j

# Load packaged subset into Neo4j, then embed + index
uv run python -m ingestion.load_graph --replace-existing
uv run python -m ingestion.build_index
```

Details: [docs/setup/movie-graph-ingestion.md](docs/setup/movie-graph-ingestion.md).

### 4. Backend

```bash
uv run uvicorn api.main:app --reload --app-dir apps/backend/src --port 8000
```

- OpenAPI: `http://localhost:8000/docs`
- Liveness: `GET /health`
- Readiness: `GET /ready`

### 5. Agent (LangGraph Studio / local CLI)

Optional for graph debugging; production chat traffic goes through the **backend**, which compiles the graph with Postgres checkpointer + store:

```bash
cd apps/agents
uv run langgraph dev
```

### 6. Frontend

```bash
cd apps/frontend
pnpm install
pnpm dev
```

Open `http://localhost:3000`, sign in via Supabase, then chat.

### 7. Full Compose stack

```bash
docker compose up --build
```

See [docs/setup/deployment.md](docs/setup/deployment.md) for production topology, secrets, and CI.

## Development commands

| Command | Purpose |
|---------|---------|
| `uv run ruff check` / `uv run ruff format` | Lint / format |
| `uv run pyright` | Type check |
| `uv run pytest` | Agents + backend tests |
| `pre-commit run --all-files` | Local git hooks (ruff + basic file hygiene) |

CI runs lint → format check → pyright → pytest on every PR and push to `main` (`.github/workflows/ci.yml`).

## Architecture (short)

```
Browser (Next.js)
    │  Bearer JWT
    ▼
FastAPI (apps/backend)
    │  builds graph with PostgresSaver + PostgresStore
    ▼
LangGraph: route → (converse | retrieve → generate)
    │
    ├─ Neo4j (movies, people, genres, keywords + vector/full-text indexes)
    └─ Supabase Postgres (auth JWKS, chat tables, LangGraph memory)
```

Retrieval always grounds answers in graph context (fail-closed when empty). Generated Cypher is validated read-only before `execute_read`.

## Documentation

- [Movie graph ingestion](docs/setup/movie-graph-ingestion.md)
- [Deployment runbook](docs/setup/deployment.md)
- [GraphRAG approaches](docs/graphrag-approaches-explained.md)
- [Production readiness review](docs/PRODUCTION_READINESS_REVIEW.md)

## License

Proprietary / project-specific — set by the repository owner.
