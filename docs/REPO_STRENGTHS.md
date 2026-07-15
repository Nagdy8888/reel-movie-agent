# Reel — What the Repository Does Well

**Project:** Reel — GraphRAG Movie Assistant (uv monorepo)
**Author:** AI code review (Cursor)
**Date:** 2026-07-14
**Purpose:** A catalogue of the practices this codebase follows well — clean code, architecture/structure, authentication, security, resilience, observability, data handling, testing, and documentation. This is the positive counterpart to the [SYSTEM_DESIGN_REVIEW.md](SYSTEM_DESIGN_REVIEW.md) and [PRODUCTION_READINESS_REVIEW.md](PRODUCTION_READINESS_REVIEW.md).

**Verified signals:** `ruff` clean · `pyright` 0 errors · **71 tests passing** · docstrings enforced in lint.

---

## 1. Clean code

### 1.1 Small, single-responsibility functions
Functions do one thing and read top-to-bottom. Private helpers are `_`-prefixed to signal intent (`_latest_question`, `_format_movie_context`, `_node_artifact`, `_resolve_movie_ids`, `_sanitize_title`). The largest module (`agents/artifacts.py`) is cohesive — everything is "turn retrieval text into UI artifacts" — rather than a grab-bag.

### 1.2 Pure logic separated from I/O
Parsing/formatting is pure and testable (`extract_movie_ids`, `sources_from_candidates`, `_parse_tags`, `_compose_document`); database access is isolated in thin `_read`/`_write` closures handed to `session.execute_read` / `execute_write`. Side effects never hide inside "pure-looking" helpers.

### 1.3 Named constants, no magic numbers
Thresholds and budgets are named at module top: `MAX_GENERATION_CONTEXT_CHARS`, `MAX_CYPHER_ATTEMPTS`, `MAX_CANDIDATE_CHARS`, `_MAX_GRAPH_MOVIES`, `DEFAULT_BATCH_SIZE`, `MAX_OVERVIEW_CHARS`.

### 1.4 No duplication, no god files
No copy-pasted functions or classes across `apps/agents` / `apps/backend`. Transport, business logic, and persistence live in separate modules. Retrieval Cypher that looks similar (`MOVIE_CONTEXT_QUERY` vs `FALLBACK_MOVIES_QUERY`) is intentionally distinct (seed-expansion vs top-rated fallback), not accidental duplication.

### 1.5 Consistent modern style
`X | None` over `Optional`; f-strings; `pathlib`; `enumerate`/comprehensions; ruff-enforced import order and formatting. One consistent voice across both Python apps.

---

## 2. Architecture & structure

### 2.1 Strict one-way dependencies
`frontend → backend → agents → (Neo4j, Postgres, OpenAI)`. `agents` never imports `backend`; the backend consumes the agent only through the compiled graph and the public `agents.artifacts` / `agents.clients` API. This boundary is the repo's strongest structural property and it holds everywhere.

### 2.2 Predictable module map
| Concern | Home |
|---------|------|
| Graph assembly | `agents/graph.py` |
| Node logic | `agents/nodes.py` |
| Retrieval + tools | `agents/tools.py` |
| UI artifacts (DTOs) | `agents/artifacts.py` |
| Prompts (versioned) | `agents/prompts/system.py` |
| Memory backends | `agents/memory.py` |
| HTTP routes | `backend/api/routes/*` |
| Auth | `backend/api/auth.py` |
| Persistence | `backend/api/services/chats.py` |
| Config | `settings.py` per app |

### 2.3 Thin routes + service layer
Handlers validate input, call an injected dependency, and shape the response — no business logic, file I/O, or graph orchestration in the transport layer (`routes/chats.py`, `routes/graph.py`). Business logic sits in services (`ChatStore`, `titles.py`) and the agent.

### 2.4 Clean dependency injection
FastAPI `Depends` aliases (`GraphDep`, `ChatStoreDep`, `UserDep`, `SettingsDep`) make routes declarative and trivially testable via `app.dependency_overrides`. The compiled graph and DB pools are built once in `lifespan` and injected — no lazy in-handler imports.

### 2.5 Design patterns applied appropriately
Cached factory/singleton (`@lru_cache` clients), repository (`ChatStore`), application factory (`create_app` + `lifespan`), strategy-by-routing (`route → _next_after_route`), template method (`Text2CypherTemplate`), DTO/typed-contract (`TypedDict` + Pydantic models), guard clause / fail-closed (`ensure_read_only`, empty-context `generate`), and cross-cutting middleware.

---

## 3. Authentication & authorization

### 3.1 Real JWT auth at the boundary
Supabase JWTs are verified against the project's **JWKS** (RS256/ES256) with audience checking, via a cached `PyJWKClient` (`api/auth.py`). The verified `sub`/`email` become a typed `User`.

### 3.2 Auth enforced at the router level
Protected routers declare `dependencies=[Depends(current_user)]` (`routes/chats.py`, `routes/graph.py`) so no endpoint is accidentally left open; public routes (`/health`, `/ready`) are the explicit exception. `HTTPBearer(auto_error=True)` rejects missing credentials with 401.

### 3.3 Per-user tenancy on every query
`ChatStore` scopes **every** statement by `user_id`. Cross-user access is denied precisely: `upsert_conversation` uses `ON CONFLICT (thread_id) DO UPDATE … WHERE conversations.user_id = EXCLUDED.user_id` (returns nothing → 403), and reads/deletes filter `AND user_id = %s` (missing → 404). Ownership can't be bypassed by guessing IDs.

---

## 4. Security

### 4.1 Read-only Cypher enforcement (injection defense)
All LLM-generated Cypher passes `ensure_read_only` (write-clause guard, now literal/comment-aware) and executes inside `session.execute_read`. Queries are typed `LiteralString`, so raw user text can't reach the driver as a query. Ingestion index names are validated against a strict identifier regex before any string interpolation.

### 4.2 Fail-closed generation (anti-hallucination)
When retrieval returns no context, `generate` returns a fixed "not enough information" reply and makes **no LLM call** — the model can't fabricate from an empty context. Prompts (`GENERATE_SYSTEM_V3`) further forbid using outside knowledge and require citing titles present in context.

### 4.3 Transport hardening
- CORS **allowlist** with a prod fail-fast (`_validate_env` refuses placeholder/`*` values when `APP_ENV=prod`).
- Security-headers middleware: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, HSTS, `Cache-Control: no-store`.
- Rate limiting on `/chat` (`slowapi`).
- Generic 500 body + `request_id`; full trace logged server-side only — **no `str(exc)` leakage**.

### 4.4 Secrets & least privilege
Secrets come from `.env`/env only, never hardcoded; `.env` is git-ignored (`!.env.example` kept). The browser gets the **publishable/anon** Supabase key, never the service role. Containers run **non-root** (backend and, after hardening, agents). LLM calls always set `timeout` and `max_tokens` (bounded cost/latency).

### 4.5 Git hygiene
Dev-only artifacts (LangGraph `.langgraph_api/*.pckl` state) are ignored and untracked; `.next/`, `node_modules/`, caches, and `*.pem` are ignored. No credentials or build state in version control.

---

## 5. Resilience & correctness

- **Per-node retries** — every graph node registered with `RetryPolicy(max_attempts=3)`.
- **Bounded self-correction** — `run_graph_query` feeds Neo4j errors/empty results back to the LLM up to `MAX_CYPHER_ATTEMPTS`, then stops (no runaway loops).
- **Fail-open where safe** — `run_rerank` returns original candidates on any error, so reranking never blocks an answer.
- **Graceful fallback** — empty recommendation turns fall back to well-reviewed movies instead of a dead end.
- **Negative-cache avoidance** — `full_graph()` refuses to cache empty snapshots, so a transient Neo4j outage can't poison the cache.
- **Correct readiness signal** — `/ready` returns 503 (not 500) when a dependency is unreachable.
- **Ingestion robustness** — idempotent `MERGE` upserts, batched transactions, manifest count verification, Aura-Free limit guard, `tenacity` retries on embeddings.

The design deliberately chooses **fail-closed for answer correctness** and **fail-open for quality enhancements** — the right call on each path.

---

## 6. Concurrency correctness

- Async web layer with sync drivers reconciled via `run_in_threadpool` / `iterate_in_threadpool`, so the event loop never blocks on psycopg / sync checkpointer / Neo4j sessions.
- The SSE generator streams graph events through a threadpool iterator, keeping the sync checkpointer working portably (including Windows).
- Clients and pools are process-lifetime singletons with a defined open/close lifecycle in `lifespan`.

---

## 7. Observability

- **Structured JSON logging** (`pythonjsonlogger`) configured process-wide.
- **Request correlation** — `RequestContextMiddleware` assigns/echoes `X-Request-ID`, binds it to logs, records per-request latency, and returns it in error bodies for support triage.
- **Distributed tracing** — LangSmith bridged from settings into process env at startup; every run tagged with `run_name`, `tags`, and `metadata` (`thread_id`, `user_id`) so traces filter by conversation and user.

---

## 8. Data handling

- **Identity on stable external IDs** (`Movie.tmdbId`, `Person.tmdbId`), not display strings; titles/names explicitly treated as non-unique. Uniqueness constraints + a title index created during ingestion.
- **Hybrid retrieval** — a 1,536-dim cosine vector index plus a multi-property full-text index, both rebuilt deterministically and awaited online before use.
- **Polyglot persistence used correctly** — graph DB for relationships/traversal, Postgres for transactional chat + LangGraph memory, vector/full-text indexes for semantic seeds.
- **Deterministic, verifiable ingestion** — a packaged, versioned bundle with a manifest the loader cross-checks (fails on drift).

---

## 9. API design

- `response_model=` on JSON routes; Pydantic models with `Field(description=...)` on every field (feeds OpenAPI + env docs for free).
- Input validation at the edge (`ChatRequest.message` has `min_length`/`max_length`).
- Correct status semantics: 401 (unauth), 403 (not owner), 404 (missing), 204 (delete), 503 (not ready).
- Well-formed SSE contract: typed `meta`/`sources`/`graph`/token/`done` frames with anti-buffering headers; a `ChatEvent` discriminated union mirrors it on the frontend.
- A thoughtful product detail: sources/graph are re-filtered to the movies actually **cited in the answer** (`filter_artifacts_by_answer`) so the right pane matches the reply.

---

## 10. Testing

- **71 passing tests** across the pyramid: pure functions first (Cypher safety, prompt builders, artifact parsing, state), then node wiring with fakes, then backend route-contract tests via `app.dependency_overrides`.
- **Negative paths covered** — auth-required, 403/404 ownership, write-clause rejection, empty-context fail-closed.
- Tests carry docstrings and follow arrange-act-assert; external services are mocked (no live network), matching the repo's testing rule.

---

## 11. Documentation & tooling

- **Docstrings are mandatory and enforced** — ruff `D` (Google convention); undocumented code fails lint. LangGraph nodes use the richer contract docstring (Reads / Writes / Side effects / Failure mode), making data flow auditable from docstrings alone.
- **Field-level docs everywhere** — Pydantic/settings `Field(description=...)` power OpenAPI and env documentation.
- **Tooling gates** — `ruff` (E/F/I/UP/D/B/ASYNC), `pyright` (basic), `pytest` + `pytest-asyncio`, `pre-commit` hooks, and (added) GitHub Actions CI running all of them. Reproducible builds via `uv.lock` + `--frozen`.

---

## 12. Highlight reel (functions worth copying)

- **`full_graph()` / `_full_graph_cached()`** — cache only *successful* results; clear the cache on empty snapshots.
- **`filter_artifacts_by_answer()`** — align UI artifacts with cited movies, in citation order.
- **`ensure_read_only()`** — safety-by-construction Cypher guard; literal/comment-aware, still rejects real writes.
- **`run_graph_query()`** — bounded LLM self-correction with read-only validation on every attempt.
- **`upsert_conversation()`** — one idempotent SQL statement that enforces tenancy and upsert atomically.

---

## 13. Summary

Reel reflects mature engineering habits: **clean, single-purpose code with no duplication; strict architectural boundaries; real JWT auth with per-user tenancy; layered security with fail-closed grounding; correct async/concurrency handling; strong observability; deterministic verified data ingestion; a typed API; and enforced docstrings + a full test/CI toolchain.** These are the foundations to preserve as the remaining hardening items (see the two review docs) are addressed.
