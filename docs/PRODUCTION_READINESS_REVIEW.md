# Reel — Production Readiness Review

**Reviewed:** 2026-07-15
**Scope:** LightRAG migration, FastAPI backend, Next.js frontend, Supabase
projection, container configuration, tests, and operational readiness.

## Executive summary

Reel's runtime no longer depends on Neo4j or Text2Cypher. Retrieval uses
LightRAG local/hybrid context-only queries over a self-hosted PostgreSQL with
Apache AGE + pgvector. Supabase continues to provide auth, chat persistence,
and LangGraph memory, and now also stores the typed Movie/Person/Genre
projection used by the UI.

The implementation has strong fail-closed behavior, bounded LLM calls, JWT
protection on data/LLM routes, RLS defense-in-depth on projection tables,
pooled projection reads, generic error responses, and contract tests.

The 25-movie smoke ingest passed. A full 1,000-movie run reached the OpenAI API
limit after 506 processed documents. The deployed data plane was finalized at
the largest fully processed deterministic prefix: **503 movies**, all with
posters and matching Supabase projection rows. Completing the originally
planned 1,000 remains optional follow-up work when quota is available.

## Current security controls

- No LLM-generated Cypher. LightRAG receives user text and returns context via
  `aquery(..., only_need_context=True)`.
- The RAG Postgres role is intentionally read/write because query-time
  LightRAG cache writes use `PGKVStorage`.
- `/chat` and `/graph` require Supabase JWT auth. The privileged
  `SUPABASE_DB_URL` bypasses RLS, so route auth is the runtime enforcement
  boundary.
- The frontend's Next.js 16 proxy validates Supabase claims and refreshes auth
  cookies before `/chat` renders; OAuth and recovery flows use a same-origin
  PKCE callback route.
- Projection tables have RLS enabled plus authenticated SELECT policies,
  closing the PostgREST/Data API path for anonymous callers.
- OpenAI calls have configured timeout and token limits and are wrapped for
  LangSmith token tracing.
- CORS uses an explicit allowlist; the global exception handler returns a
  generic body with a request ID.
- Backend and agent containers run as a non-root user.

## Dependency readiness

`GET /ready` verifies:

1. the AGE+pgvector Postgres accepts `SELECT 1`;
2. the application's existing Supabase connection pool passes `check()`;
3. the LangGraph checkpointer can execute a read.

The backend closes its chat pool, projection pool, and initialized LightRAG
stores during shutdown.

## Data and ingestion readiness

The ingestion pipeline:

- joins CMU plot, movie, and character metadata by numeric Wikipedia ID;
- selects a deterministic top 1,000 by box office and numeric Wikipedia ID;
- fetches TMDB posters with bounded concurrency and retry handling;
- idempotently refreshes projection edges and upserts nodes;
- inserts one LightRAG document per movie with
  `id=file_path=movie:{wikipedia_id}`;
- uses LightRAG's public `aget_docs_by_ids()` status API for resumability;
- treats `--limit` as the authoritative projection size and prunes stale
  projection rows;
- validates projection counts, referential integrity, and processed document
  statuses.

Required deployment sequence:

```bash
docker compose up -d rag-postgres
uv run python -m ingestion.ingest --limit 25
uv run python -m ingestion.ingest --limit 1000
```

The smoke query returned `movie:1213838` from local context. The quota-limited
run can later resume with `--limit 1000`; processed documents are skipped.
LangSmith LLM runs with non-zero token counts were confirmed, and a live
backend `/ready` request returned HTTP 200 against both databases and the
checkpointer.

## Open operational risks

### Medium — original 1,000-movie target is partially loaded

The current consistent subset is 503 movies. LightRAG contains three additional
processed documents outside that prefix plus interrupted pending/in-progress
status rows from the stopped 1,000 run; those extra documents are not exposed
by the UI projection. Resume the 1,000 run when quota is available.

### Medium — agent Compose service is development-only

`apps/agents` runs `langgraph dev` for Studio. Production traffic should use
the FastAPI backend, which compiles the graph with the Supabase checkpointer
and store, or use a supported production LangGraph deployment.

### Medium — Docker base tags float

Python, Node, and uv image tags are not digest-pinned. Pin them before a
strictly reproducible production release.

### Medium — full graph cache requires invalidation after ingestion

`full_graph()` intentionally caches a successful projection snapshot. Restart
the backend or call `full_graph.cache_clear()` after a projection reload.

### Low — dependency advisors outside migration scope

Supabase's projection tables have no current security/performance findings.
Existing project-wide advisories remain for checkpointer/store tables without
Data API policies, auth leaked-password protection, and legacy chat-policy
init plans. They do not originate from the projection migration, but should be
handled in a separate Supabase hardening change.

## Release gate

- Python lint/format/type/tests must pass.
- Frontend ESLint, TypeScript, Vitest, production build, and
  focused/performance Playwright tests must pass in CI.
- `docker compose config` and the `rag-postgres` healthcheck must pass.
- 25-movie smoke ingest must pass.
- The current 503-movie subset must pass validation; a full 1,000-movie ingest
  remains the gate only if the original corpus-size target is required.
- Manual local/hybrid answer checks and LangSmith token-trace verification
  must pass.

The 503-movie deployment can be used now. Do not claim that the original
1,000-movie data target is complete until a resumed full run validates.
