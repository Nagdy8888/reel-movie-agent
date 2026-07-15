# Deployment runbook

How to take Reel from a working local stack to a production-facing deployment. Companion to the root [README](../../README.md) and [movie-graph-ingestion](movie-graph-ingestion.md).

## Recommended production topology

| Component | Deploy? | Notes |
|-----------|---------|--------|
| `apps/backend` | **Yes** | Public HTTP API. Compiles the LangGraph agent with Postgres checkpointer + store in lifespan. |
| `apps/frontend` | **Yes** | Next.js (standalone Docker image or Vercel/hosting). Talks only to the backend + Supabase Auth. |
| LightRAG Postgres (AGE + pgvector) | **Yes** | **Self-hosted** only (Compose/`rag-postgres`, VM, Fly, Railway). Managed DBaaS — including Supabase — does not offer Apache AGE. Single-instance (working dir + PG). |
| Supabase | **Yes** | Auth (JWKS) + Postgres for chat, LangGraph memory, and the UI projection tables. |
| `apps/agents` Compose service (`langgraph dev`) | **No (prod)** | Dev/Studio only. Do not expose it on the public internet. |

If you later need a standalone agent runtime (beyond embedding the graph in the backend), use **LangGraph Platform** or `langgraph up` — not `langgraph dev`. See finding H1/H2 in [PRODUCTION_READINESS_REVIEW.md](../PRODUCTION_READINESS_REVIEW.md).

## Environment variables

Copy [`.env.example`](../../.env.example) and fill every required value. Critical production settings:

| Variable | Requirement in prod |
|----------|---------------------|
| `APP_ENV` | Must be `prod`. Backend refuses boot if CORS / Supabase values look like placeholders or `*`. |
| `CORS_ALLOW_ORIGINS` | Explicit frontend origin(s), comma-separated. Never `*`. |
| `SUPABASE_URL` | Project URL used for JWKS JWT verification. |
| `SUPABASE_DB_URL` | Direct Postgres URL for checkpointer, store, chat, and projection reads/writes. |
| `SUPABASE_JWT_AUD` | Usually `authenticated`. |
| `OPENAI_API_KEY` | Required for chat, LightRAG extraction/query, rerank, embeddings. |
| `RAG_PG_HOST` / `RAG_PG_PORT` / `RAG_PG_USER` / `RAG_PG_PASSWORD` / `RAG_PG_DATABASE` | AGE+pgvector Postgres for LightRAG's four stores. |
| `RAG_PG_WORKSPACE` | LightRAG workspace isolation (default `reel`). |
| `LIGHTRAG_WORKING_DIR` | Persistent working dir for LightRAG artifacts. |
| `TMDB_API_ACCESS_TOKEN` | Poster enrichment during ingestion. |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_TOKENS` | Keep bounded (defaults in `.env.example`). |
| `LANGSMITH_*` | Recommended for production observability (token traces). |

Frontend build-time public vars (e.g. Docker build-args / hosting env):

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | Browser Supabase client |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Publishable anon key only — never the service role |
| `NEXT_PUBLIC_API_URL` | Backend base URL (HTTPS in prod) |

**Never commit** `.env`, `apps/frontend/.env.local`, or service-role keys. Rotate OpenAI, Supabase, TMDB, and LangSmith credentials if they ever appear in logs or a leaked commit.

Inside Compose, set `RAG_PG_HOST=rag-postgres` on `agent`/`backend`.
Host-side `.env` keeps `RAG_PG_HOST=localhost` with port `55432`; Compose
overrides app containers to `rag-postgres:5432`.

## Database / memory setup

### Supabase Postgres (chat + LangGraph + UI projection)

On backend startup, lifespan calls:

1. `build_checkpointer()` → `PostgresSaver.setup()` (checkpoint tables if missing)
2. `build_store()` → `PostgresStore.setup()` (store tables if missing)
3. `open_pool()` for the `ChatStore` (conversations / messages)

UI projection tables (`movies`, `people`, `genres`, `acted_in`, `in_genre`) are created via Supabase migrations (RLS on, authenticated SELECT). The backend reads them over `SUPABASE_DB_URL` (bypasses RLS); `/graph` and chat still require JWT auth.

### LightRAG AGE Postgres + hybrid ingest

Cold start or rebuild:

```bash
docker compose up -d rag-postgres
uv run python -m ingestion.ingest --limit 25     # smoke
uv run python -m ingestion.ingest --limit 1000   # full
```

Full steps: [movie-graph-ingestion.md](movie-graph-ingestion.md).

The RAG role is **read/write** (query path writes an LLM cache). Readiness (`GET /ready`) probes LightRAG Postgres, Supabase, and the checkpointer.

## Build and run (containers)

From the repo root with a filled `.env` (and frontend public vars available to Compose):

```bash
docker compose up --build
```

Typical ports:

| Service | Port |
|---------|------|
| frontend | 3000 |
| backend | 8000 |
| agent (dev) | 2024 |
| rag-postgres | 55432 → 5432 |

## Production (EC2 + Vercel)

| Piece | Where | How it updates |
|-------|--------|----------------|
| Backend + `rag-postgres` | EC2 (`/opt/reel`) | Push to `main` → CI builds/pushes GHCR images → SCP syncs compose → `deploy.sh` |
| Frontend | Vercel project `reel-frontend` | Redeploy from `apps/frontend` (or linked Git) |
| Supabase projection | Shared cloud DB | Already populated by local/hybrid ingest |

### EC2 `.env` must include LightRAG vars

On the host file `/opt/reel/.env` (read by Compose `env_file`), add at least:

```bash
RAG_PG_USER=lightrag
RAG_PG_PASSWORD=<strong-secret>
RAG_PG_DATABASE=lightrag
RAG_PG_WORKSPACE=reel
# Compose overrides host/port inside the backend container:
#   RAG_PG_HOST=rag-postgres  RAG_PG_PORT=5432
OPENAI_API_KEY=...
SUPABASE_URL=...
SUPABASE_DB_URL=...
CORS_ALLOW_ORIGINS=https://reel-frontend-six.vercel.app
APP_ENV=prod
SUBSET_SIZE=503
```

Remove obsolete `NEO4J_*` keys. Backend readiness (`GET /ready` on the Caddy URL) fails until AGE Postgres is healthy **and** LightRAG has ingested data on that volume.

### First LightRAG boot on a new EC2 volume

Supabase projection can already have the 503-movie UI graph from a prior ingest, but the EC2 `rag_pg_data` volume starts empty. Either:

1. **Re-ingest on the server** (costs OpenAI tokens again), e.g. run the ingest module against the compose network with `--limit 503`, or
2. **Restore** a `pg_dump` of a known-good local `rag_pg_data` onto EC2.

Until one of those is done, retrieval fails closed even if `/health` is fine.

## CI

GitHub Actions should run the Python gate (`ruff`, `ruff format --check`, `pyright`, `pytest`) and frontend `lint` + `tsc`. Do not call live OpenAI/TMDB/DB from unit tests.

## Rollback

- **App:** redeploy the previous backend/frontend image or Vercel deployment.
- **Projection:** restore Supabase from backup, or re-run ingest (idempotent upserts).
- **LightRAG stores:** restore the `rag_pg_data` volume / VM disk, or wipe and re-ingest (LightRAG doc status makes restarts safe; full re-extraction costs LLM tokens again).
