# Build Phases — GraphRAG Movie Agent ("Reel")

This folder breaks the project in `.cursor/plans/graphrag_movie_agent_e5678c2b.plan.md` into small, ordered, **self-contained** phases. Do them **in order**. Each phase ends in a working, verifiable state before the next begins.

The phases go from **low level → high level**: a tiny working agent first, then data, then retrieval, then the API, then auth/security, tests, the UI, deployment, and docs.

## How to use these files (read this every time)

1. Open the current phase file and do **only** that phase.
2. Before writing code, remember the always-on rules in `.cursor/rules/` — they are mandatory:
   - `project-structure` — where files go (everything under `apps/`).
   - `documentation` — **every function/class/module needs a docstring** (ruff `D`).
   - `security` — read-only Cypher, `hmac.compare_digest`, LLM `timeout`+`max_tokens`, no secrets in logs.
   - plus `python-standards`, `fastapi-backend`, `langgraph-agent`, `frontend`, `testing` (auto-attached by file type).
3. Use the skills in `.cursor/skills/` when they apply (`add-api-route`, `add-agent-node`, `port-stitch-screen`, `verify-standards`).
4. After finishing a phase, run its **Acceptance criteria** checklist. Do not move on until every box passes.
5. Never invent file locations — follow the exact paths given.

## Supabase — use the MCP plugin (connected)

The **Supabase Cursor plugin** is installed and authenticated. Perform Supabase work **through the MCP tools**, not the dashboard or hand-written SQL strings. See the always-on rule `.cursor/rules/supabase-mcp.mdc`.

- **Target project:** `Reel` — `project_id: "bkhmqtcxoxtrydumgwfd"`, URL `https://bkhmqtcxoxtrydumgwfd.supabase.co` (region eu-north-1). It is currently empty.
- **DDL** (tables/indexes/RLS) → `apply_migration`. **Queries/checks** → `execute_sql`. **Inspect** → `list_tables`, `list_migrations`, `list_extensions`. **Config** → `get_project_url`, `get_publishable_keys`. **After schema changes** → `get_advisors`. **Docs** → `search_docs`.
- **Never hardcode keys** into committed files — fetch via MCP into `.env` / `.env.local`.

## Global conventions (apply to all phases)

- **OS / shell:** Windows + PowerShell. Commands are written for PowerShell.
- **Package manager:** `uv` (Python) and `pnpm` (frontend). Always run Python via `uv run ...`.
- **Python:** 3.11+. **LLM provider:** OpenAI (`OPENAI_API_KEY`). Chat
  model `gpt-4o-mini` by default; embeddings `text-embedding-3-small`
  (1,536 dimensions).
- **Secrets:** live only in the root `.env` (already present). Never hardcode keys. Never print/log secrets. Keep `.env.example` updated with variable names + comments (no real values).
- **Docstrings are mandatory** on every module, class, function, and method. LangGraph nodes use the contract docstring (reads/writes/side effects/failure mode).
- **Verify after every phase** using the `verify-standards` skill where Python is involved.

## Phase list (do in this order)

| # | File | Outcome |
|---|------|---------|
| 1 | `phase-01-scaffold.md` | uv-workspace monorepo, `apps/` skeleton, tooling (ruff/pyright/pre-commit), `.env.example`. |
| 2 | `phase-02-minimal-agent.md` | A simple LangGraph agent that replies, visible in LangGraph Studio, traced in LangSmith, runnable via Docker. |
| 3 | `phase-03-neo4j-ingestion.md` | Top 5,000 Kaggle movies loaded; composed embeddings and hybrid indexes built. |
| 4 | `phase-04-graphrag-agent.md` | Agent upgraded to GraphRAG: read-only Cypher tool + vector tool + router; checkpointer + store. |
| 5 | `phase-05-backend-api.md` | FastAPI backend wrapping the agent: `/chat` SSE streaming, `/health` + `/ready`, Dockerized. |
| 6 | `phase-06-auth-security.md` | Supabase JWT auth on routes + CORS allowlist + rate limiting + security headers + generic errors. |
| 7 | `phase-07-tests.md` | pytest suite: pure-function unit tests + route contract tests. |
| 8 | `phase-08-frontend.md` | Next.js app: port the 3 Stitch screens, wire Supabase auth + SSE chat + Sources/Graph panels. |
| 9 | `phase-09-deploy.md` | Deploy: backend to EC2 free-tier + Caddy TLS, frontend to Vercel, Aura + Supabase; CI. |
| 10 | `phase-10-docs.md` | C4 docs + `docs/setup/` guides + final README. |

## Definition of done for the whole project

All 10 phases pass their acceptance criteria; `verify-standards` is green; the app runs locally via `docker compose up` and answers a movie question end-to-end with sources.
