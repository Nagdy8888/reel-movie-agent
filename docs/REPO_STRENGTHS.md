# Repository Strengths

**Reviewed:** 2026-07-15

## Clear component ownership

- `apps/agents` owns LangGraph, LightRAG integration, retrieval, projection
  adaptation, and ingestion.
- `apps/backend` owns HTTP transport, auth, rate limiting, persistence, and
  SSE contracts.
- `apps/frontend` owns the Next.js/Sigma experience.

The agent package does not import backend or frontend code. The backend
consumes the agent through public graph/artifact APIs.

## Deliberate two-store architecture

The repository does not force LightRAG's free-form extraction graph into the
typed UI contract:

- self-hosted AGE+pgvector Postgres stores LightRAG internals;
- Supabase stores auth, chat, memory, and the UI Movie/Person/Genre projection.

This keeps retrieval quality and UI stability independent while stable
`movie:{wikipedia_id}` file-path keys bridge them.

## Grounding and failure behavior

- Local and hybrid searches request context only.
- Explicit movie keys are recovered before projection-title fallback.
- Unmappable retrieval is discarded before generation.
- Empty context returns a fixed refusal without an LLM call.
- Recommendation fallback uses real projection rows ordered by box office.
- Reranking is fail-open and preserves original context/key tokens.

## Async and resource lifecycle

- Sync LangGraph nodes use one persistent background event loop for cached
  LightRAG async resources.
- OpenAI clients and projection connections are shared/cached.
- Ingestion bounds TMDB and LightRAG concurrency.
- Backend shutdown closes application/projection pools and initialized
  LightRAG stores.
- Readiness checks the RAG database, existing Supabase pool, and checkpointer.

## Security

- JWT dependencies protect non-public data and LLM routes.
- CORS uses an explicit allowlist.
- LLM calls set timeouts and token caps.
- No model-generated SQL or Cypher reaches a database.
- Projection RLS protects the PostgREST path, while route auth protects
  privileged direct-Postgres reads.
- Generic exception responses avoid leaking internals.
- Containers run as non-root users.

## Data pipeline

The CMU loader has deterministic subset selection, strict stable IDs,
bounded/retried TMDB enrichment, idempotent projection refresh, public
LightRAG status-based resumability, and post-load integrity checks.

## Contracts and tests

Pydantic API models keep stable source and graph payloads. Tests cover:

- CMU parsing, subset ordering, and ID quoting;
- LightRAG mode delegation and status APIs;
- persistent async bridging;
- key/title recovery and fail-closed behavior;
- projection hydration and full-graph caching;
- LangGraph node behavior;
- backend health/chat/graph contracts;
- frontend focused and large synthetic graph behavior.

## Documentation discipline

The root README, setup guides, deployment runbook, architecture review, and
security guidance all describe the same LightRAG/Supabase storage split and
the live-ingestion verification boundary.
