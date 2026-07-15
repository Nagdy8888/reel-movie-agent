# Reel — GraphRAG Movie Assistant

Reel is a uv-workspace monorepo for a movie Q&A and recommendation assistant.
Natural-language questions are grounded via **LightRAG** (local/hybrid
context retrieval over a CMU MovieSummaries subset) plus a typed
Movie/Person/Genre **Supabase projection** for the Sigma graph UI. A FastAPI
backend with Supabase JWT auth serves the Next.js chat app.

## Monorepo layout

| Path | Role |
|------|------|
| `apps/agents` | LangGraph deployable — graph, nodes, LightRAG retrieval, hybrid ingestion |
| `apps/backend` | FastAPI HTTP layer — auth, chat SSE, chat history, readiness |
| `apps/frontend` | Next.js App Router UI (chat, sources, graph canvas) |
| `docs/` | Architecture notes, setup guides, reviews |
| `datasets/MovieSummaries/` | CMU corpus (not committed; download locally) |

**Placement rule:** graph/retrieval logic lives in `apps/agents`; HTTP transport lives in `apps/backend` (imports the compiled graph). No reverse imports.

## Prerequisites

- Python **3.11+** and [uv](https://docs.astral.sh/uv/)
- Node **20+** and [pnpm](https://pnpm.io/) (frontend)
- Docker (for local AGE+pgvector Postgres via `docker-compose`)
- Accounts / keys: OpenAI, Supabase (auth + Postgres), TMDB (posters), LangSmith (tracing)

## Quick start (local)

### 1. Environment

```bash
cp .env.example .env
# Fill OPENAI_*, RAG_PG_*, SUPABASE_*, TMDB_API_ACCESS_TOKEN, LANGSMITH_*, CORS_ALLOW_ORIGINS
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

### 3. LightRAG Postgres + hybrid ingest

```bash
docker compose up -d rag-postgres

# Place CMU files under datasets/MovieSummaries/, then:
uv run python -m ingestion.ingest --limit 25    # smoke
# uv run python -m ingestion.ingest --limit 1000  # full (hours)
```

Details: [docs/setup/movie-graph-ingestion.md](docs/setup/movie-graph-ingestion.md).

### 4. Backend

```bash
uv run uvicorn api.main:app --reload --app-dir apps/backend/src --port 8000
```

- OpenAPI: `http://localhost:8000/docs`
- Liveness: `GET /health`
- Readiness: `GET /ready` (LightRAG Postgres + Supabase + checkpointer)

### 5. Agent (LangGraph Studio / local CLI)

Optional for graph debugging; production chat traffic goes through the **backend**:

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

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
pnpm --dir apps/frontend lint
pnpm --dir apps/frontend tsc --noEmit
```

## Architecture snapshot

- **Retrieval:** LightRAG `local` (facts) + `hybrid` (plot/theme), context-only;
  movie keys recovered from `movie:{wikipedia_id}` file_path tokens, with a
  title fallback against the projection.
- **UI graph:** Supabase projection tables (not the LightRAG AGE graph).
- **Memory / auth:** Supabase Postgres checkpointer/store + JWT.
- **Tracing:** LangSmith for ingestion and query-time LLM calls.
