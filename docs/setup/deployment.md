# Deployment runbook

How to take Reel from a working local stack to a production-facing deployment. Companion to the root [README](../../README.md) and [movie-graph-ingestion](movie-graph-ingestion.md).

## Recommended production topology

| Component | Deploy? | Notes |
|-----------|---------|--------|
| `apps/backend` | **Yes** | Public HTTP API. Compiles the LangGraph agent with Postgres checkpointer + store in lifespan. |
| `apps/frontend` | **Yes** | Next.js (standalone Docker image or Vercel/hosting). Talks only to the backend + Supabase Auth. |
| Neo4j | **Yes** | Aura or self-hosted. Prefer TLS (`neo4j+s://`) in prod. |
| Supabase | **Yes** | Auth (JWKS) + Postgres for chat tables and LangGraph memory. |
| `apps/agents` Compose service (`langgraph dev`) | **No (prod)** | Dev/Studio only. Do not expose it on the public internet. |

If you later need a standalone agent runtime (beyond embedding the graph in the backend), use **LangGraph Platform** or `langgraph up` — not `langgraph dev`. See finding H1/H2 in [PRODUCTION_READINESS_REVIEW.md](../PRODUCTION_READINESS_REVIEW.md).

## Environment variables

Copy [`.env.example`](../../.env.example) and fill every required value. Critical production settings:

| Variable | Requirement in prod |
|----------|---------------------|
| `APP_ENV` | Must be `prod`. Backend refuses boot if CORS / Supabase values look like placeholders or `*`. |
| `CORS_ALLOW_ORIGINS` | Explicit frontend origin(s), comma-separated. Never `*`. |
| `SUPABASE_URL` | Project URL used for JWKS JWT verification. |
| `SUPABASE_DB_URL` | Direct Postgres URL for checkpointer, store, and chat persistence. |
| `SUPABASE_JWT_AUD` | Usually `authenticated`. |
| `OPENAI_API_KEY` | Required for chat, Text2Cypher, rerank, embeddings (ingestion). |
| `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` / `NEO4J_DATABASE` | Graph store credentials. |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_TOKENS` | Keep bounded (defaults in `.env.example`). |
| `LANGSMITH_*` | Optional but recommended for production observability. |

Frontend build-time public vars (e.g. Docker build-args / hosting env):

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | Browser Supabase client |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Publishable anon key only — never the service role |
| `NEXT_PUBLIC_API_URL` | Backend base URL (HTTPS in prod) |

**Never commit** `.env`, `apps/frontend/.env.local`, or service-role keys. Rotate OpenAI, Supabase, Neo4j, and LangSmith credentials if they ever appear in logs or a leaked commit.

## Database / memory setup

### Supabase Postgres (chat + LangGraph)

On backend startup, lifespan calls:

1. `build_checkpointer()` → `PostgresSaver.setup()` (checkpoint tables if missing)
2. `build_store()` → `PostgresStore.setup()` (store tables if missing)
3. `open_pool()` for the `ChatStore` (conversations / messages)

Ensure `SUPABASE_DB_URL` points at a role that can create those tables on first boot (or pre-apply equivalent schema via migrations if your org forbids auto-DDL). Chat tables (`conversations`, `messages`) must exist with RLS/policies appropriate for your Supabase project — apply schema through your usual migration path before opening traffic.

### Neo4j graph data

Cold start (empty database) or full rebuild:

```bash
uv run python -m ingestion.load_graph --replace-existing
uv run python -m ingestion.build_index
```

`--replace-existing` **deletes** the existing graph. Use only when intentional. After a stable first load, omit it for idempotent merges. Full steps and counts: [movie-graph-ingestion.md](movie-graph-ingestion.md).

Verify indexes (`movie_plot_embeddings`, `movie_fulltext`) are online before sending chat traffic.

On Neo4j Enterprise / Aura Pro, prefer a **dedicated read-only DB user** for the agent/runtime while keeping write credentials only for ingestion jobs.

## Build and run (containers)

From the repo root with a filled `.env` (and frontend public vars available to Compose):

```bash
docker compose up --build
```

Typical ports:

| Service | Port |
|---------|------|
| Frontend | 3000 |
| Backend | 8000 |
| Neo4j Bolt / Browser | 7687 / 7474 |
| LangGraph Studio (dev only) | 2024 |

Production checklist for images:

- Backend already runs as non-root and defines a `HEALTHCHECK` on `/health`.
- Agents image also drops to non-root; still treat it as **dev-only**.
- Pin base images / uv versions before locking a release (see M4 in the readiness review).

## Health and readiness

| Endpoint | Use |
|----------|-----|
| `GET /health` | Process liveness (cheap). |
| `GET /ready` | Dependency readiness (Neo4j + checkpointer presence). Prefer this for load-balancer readiness once M5 (Postgres probe) is also closed. |

Chat and chat-history routes require a valid Supabase Bearer JWT. Unauthenticated requests must receive `401`.

## CORS and auth

- Backend CORS allowlist = `CORS_ALLOW_ORIGINS` only.
- Frontend sends `Authorization: Bearer <access_token>` (not cookie sessions for the API).
- Rate limit on `POST /chat` is `20/minute` per client IP (`slowapi`).

## CI

GitHub Actions (`.github/workflows/ci.yml`) on push/PR to `main`:

1. `uv sync --frozen --group dev`
2. `ruff check`
3. `ruff format --check`
4. `pyright`
5. `pytest`

PRs should be green before merge. Install pre-commit locally for the same ruff hooks before push:

```bash
uv run pre-commit install
```

## Secret rotation (quick procedure)

1. Rotate the secret in the provider (OpenAI / Supabase / Neo4j / LangSmith).
2. Update the hosting platform’s secret store / `.env` used by the deployment.
3. Redeploy backend (and frontend if public Supabase URL/anon key changed).
4. Invalidate sessions if Supabase JWT signing material was rotated (usually automatic with new project keys after client refresh).
5. Confirm `/ready` is healthy and a signed-in chat turn succeeds.

## Rollback

- **App:** Redeploy the previous image tags for frontend/backend.
- **Graph:** Restore Neo4j from Aura/backup, or re-run `load_graph --replace-existing` from a known good bundle + `build_index`.
- **Postgres:** Restore Supabase point-in-time / backup if chat or checkpoint tables are corrupted (rare).

## Related docs

- [README](../../README.md) — local quick start
- [Movie graph ingestion](movie-graph-ingestion.md)
- [Production readiness review](../PRODUCTION_READINESS_REVIEW.md)
