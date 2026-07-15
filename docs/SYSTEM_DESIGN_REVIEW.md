# Reel — System Design Review

**Project:** Reel — GraphRAG Movie Assistant (uv monorepo)
**Reviewer:** AI code review (Cursor)
**Date:** 2026-07-14
**Focus:** Architecture and system-design concerns only — scalability, resilience, concurrency, state/consistency, caching, data flow, and deployment topology. Findings are categorized by severity.
**Companions:** [REPO_STRENGTHS.md](REPO_STRENGTHS.md) (what the repo does well) · [PRODUCTION_READINESS_REVIEW.md](PRODUCTION_READINESS_REVIEW.md) (code/security/ops issues).

> Scope note: This document evaluates *design*, not line-level bugs. Where a design item overlaps an operational finding in the readiness review, it's cross-referenced (e.g. H1↔SD-H3).

---

## 1. Architecture overview

Three independently deployable apps in one uv workspace with strict one-directional dependencies (`frontend → backend → agents → stores`).

```
        Browser (Next.js) ──Bearer JWT / SSE──► FastAPI backend (apps/backend)
                                                     │ owns compiled graph
                                     ┌───────────────┼──────────────────┐
                                     ▼               ▼                  ▼
                          LangGraph agent      Supabase Postgres     (rate limit,
                          route→retrieve→      chat + checkpointer   logs, auth)
                          generate|converse    + UI projection
                             │        │
                    LightRAG local/hybrid   projection reads (/graph, sources)
                             ▼                    ▲
                 AGE+pgvector Postgres     movies/people/genres tables
                 (4 LightRAG stores)
```

> **2026-07-15 update:** Neo4j / Text2Cypher retrieval was replaced by LightRAG
> over self-hosted AGE+pgvector Postgres, with a typed Movie/Person/Genre
> projection in Supabase for the UI. Some findings below still refer to the
> pre-migration stack; treat OpenAI/LightRAG/Supabase as the live dependencies.

**Request lifecycle (chat):** authenticate JWT → rate-limit → upsert conversation + persist user message → stream graph events (`route → retrieve → generate`) over SSE → emit sources/graph, then re-filter to cited movies → persist assistant message + generate title.

---

## 2. Findings by severity

| Severity | Count | IDs |
|----------|-------|-----|
| 🔴 Critical | 0 | — |
| 🟠 High | 3 | SD-H1, SD-H2, SD-H3 |
| 🟡 Medium | 6 | SD-M1 … SD-M6 |
| 🟢 Low | 5 | SD-L1 … SD-L5 |

---

### 🔴 Critical
None. There is no design flaw that blocks a controlled production launch. The system is stateless at the app tier, uses durable external stores, and fails closed on the correctness-critical path.

---

### 🟠 High

#### SD-H1 — Full-graph endpoint returns an unbounded payload
- **Area:** Scalability / data transfer
- **Location:** `apps/backend/src/api/routes/graph.py` → `agents.artifacts.full_graph()` (`_FULL_GRAPH_NODES_QUERY`, `_FULL_GRAPH_LINKS_QUERY`)
- **Detail:** `GET /graph` materializes **every** Movie/Person/Genre/Keyword node and relationship into one JSON response. For the 5k-movie seed (~48k nodes / ~136k relationships) this is already a large payload to serialize server-side and render client-side; it grows linearly with the dataset with no ceiling.
- **Impact:** Slow first paint, high memory spikes during serialization, and a heavy client render as the graph grows. A single call can dominate a worker.
- **Recommendation:** Add server-side sampling / level-of-detail (e.g. top-N by rating/popularity, or ego-graphs around a seed), pagination or a node/edge cap, and cache per-view. Keep the cached full snapshot only for small datasets.

#### SD-H2 — No circuit breaker / fast-fail for external dependencies
- **Area:** Resilience under dependency outage
- **Location:** OpenAI + LightRAG/Postgres call sites (`agents/clients.py`, `agents/tools.py`, `agents/nodes.py`)
- **Detail:** Per-call timeouts and node `RetryPolicy(max_attempts=3)` exist, but there is no breaker. When OpenAI or the RAG Postgres is down, **every** request pays the full timeout (× retries) before failing, and retries add load to an already-struggling dependency.
- **Impact:** During a sustained outage, latency balloons and threadpool/worker slots saturate — a localized dependency failure becomes a full-service brownout.
- **Recommendation:** Add a circuit breaker (e.g. `pybreaker` or a token-bucket + open/half-open state) around OpenAI and Neo4j; when open, fail fast with a friendly degraded response. Pair with `/ready` so orchestrators can shed load.

#### SD-H3 — Agent deployment topology (dev server as prod runtime)
- **Area:** Deployment architecture (overlaps readiness **H1/H2**)
- **Location:** `apps/agents/Dockerfile` (`CMD langgraph dev`), `apps/agents/langgraph.json` (wildcard CORS)
- **Detail:** The agent container runs the in-memory Studio/dev server, which is not a production runtime, and its CORS is fully permissive. Production chat already flows through the backend (which compiles the graph with the Postgres checkpointer/store), so the agent service should be dev-only or replaced by LangGraph Platform / `langgraph up`.
- **Impact:** If the agent service is deployed and exposed, you ship a dev server with open CORS as a public surface.
- **Recommendation:** Decide topology: keep the agent service dev-only (don't expose in prod), or run a real LangGraph runtime and tighten `langgraph.json` CORS. Align `docker-compose.yml` accordingly.

---

### 🟡 Medium

#### SD-M1 — Rate limiting is per-process, not distributed
- **Area:** Distributed systems / abuse control
- **Location:** `apps/backend/src/api/limiter.py` (`Limiter(key_func=get_remote_address)`, default in-memory storage)
- **Detail:** The `20/minute` limit on `/chat` is enforced per replica in local memory. With N replicas behind a load balancer the effective global limit is ~N×, and counters reset on restart.
- **Impact:** Cost/abuse controls are weaker than intended at scale; inconsistent limits across replicas.
- **Recommendation:** Back `slowapi` with a shared store (Redis) for a global limit, or enforce limits at the gateway/reverse proxy.

#### SD-M2 — Assistant-message persistence lives inside the SSE generator
- **Area:** Durability / consistency
- **Location:** `apps/backend/src/api/routes/chat.py` → `_event_stream` (final `store.add_message(..., "assistant", answer)` + title generation)
- **Detail:** The user message is persisted before streaming, but the **assistant** reply and title are written only after the stream completes, inside the async generator. If the client disconnects mid-stream (or the worker restarts), the generator is cancelled and the assistant turn is never saved — yet the checkpointer may already hold graph state, so history and memory can diverge.
- **Impact:** Lost/half-written conversation turns on disconnect; history vs. checkpointer inconsistency.
- **Recommendation:** Persist incrementally or via a post-response background task/queue that survives client disconnect; reconcile with the checkpointer thread on next load.

#### SD-M3 — In-memory caches have no TTL or invalidation
- **Area:** Cache invalidation / freshness
- **Location:** `agents/tools.py::get_graph_schema`, `agents/artifacts.py::_full_graph_cached` (`@lru_cache`)
- **Detail:** The full-graph projection snapshot is cached for the process lifetime (`full_graph` + `lru_cache`). After a re-ingestion the running backend keeps serving the stale graph until restart or `full_graph.cache_clear()`. (There is a good negative-cache guard for *empty* snapshots, but no positive-cache expiry.)
- **Impact:** Stale `/graph` view after data updates without a redeploy.
- **Recommendation:** Add a TTL (e.g. `cachetools.TTLCache`) or an explicit cache-bust hook triggered by ingestion.

#### SD-M4 — Chat-history read path loads the full thread
- **Area:** Data-access scalability
- **Location:** `apps/backend/src/api/services/chats.py::get_for_user` (selects all messages for a conversation)
- **Detail:** Fetching a conversation returns every message with no pagination. Long-lived threads grow unboundedly.
- **Impact:** Increasing latency and payload size for active users over time.
- **Recommendation:** Paginate messages (cursor by `created_at`/id) and lazy-load older history in the UI.

#### SD-M5 — Concurrency capacity is bounded by the sync threadpool
- **Area:** Concurrency / capacity planning
- **Location:** `run_in_threadpool` / `iterate_in_threadpool` usage in `routes/chat.py`, `routes/chats.py`, `routes/graph.py`; pools sized `max_size=5` in `db.py` / `memory.py`
- **Detail:** Sync DB and LLM work is offloaded to the default AnyIO threadpool (default 40 tokens) while DB pools cap at 5 connections per process. Under load the effective concurrency ceiling is the smaller of threadpool tokens and pool size, per replica.
- **Impact:** Throughput cliffs and queueing under burst traffic that aren't obvious from the async signatures.
- **Recommendation:** Size the threadpool and DB pool deliberately for expected concurrency; document the per-replica ceiling; scale replicas accordingly.

#### SD-M6 — Startup does DDL on every replica with no coordination
- **Area:** Deployment / startup coordination
- **Location:** `apps/backend/src/api/main.py::lifespan` → `build_checkpointer()` / `build_store()` call `.setup()`
- **Detail:** Each replica runs checkpointer/store `.setup()` (idempotent DDL) at boot. On a fresh multi-replica rollout, several replicas race to create the same tables. LangGraph's setup is idempotent, but concurrent DDL can still surface transient errors and slows cold start.
- **Impact:** Noisy/failed first boots on scaled cold starts; startup latency.
- **Recommendation:** Run migrations/`.setup()` as a one-off pre-deploy job (or a single init container) and have replicas assume schema exists.

---

### 🟢 Low

- **SD-L1 — No pagination on chat list.** `list_for_user` returns all conversations for a user; add a limit/cursor as users accumulate threads. (`services/chats.py`)
- **SD-L2 — Context budget is char-based, not token-based.** `MAX_GENERATION_CONTEXT_CHARS = 14_000` approximates a token budget; a tokenizer-aware trim would use the model window more precisely. (`agents/nodes.py`)
- **SD-L3 — No idempotency key on `POST /chat`.** Conversation upsert is idempotent, but a retried request re-inserts the user message (`store.add_message`). Accept a client idempotency key to dedupe retries. (`routes/chat.py`)
- **SD-L4 — Metrics gap.** Observability has structured logs + LangSmith traces but no RED/USE metrics (request rate/error/duration counters). Add Prometheus/OpenTelemetry metrics for dashboards and alerting.
- **SD-L5 — No SSE heartbeat.** Long generations behind idle-timeout proxies can be cut without a periodic keep-alive comment frame. (`routes/chat.py`)

---

## 3. System-design scorecard

| Dimension | Rating | Notes |
|-----------|:------:|-------|
| Separation of concerns | ★★★★★ | Strict one-way deps; no god files |
| Scalability (stateless app) | ★★★★☆ | Replica-friendly; watch SD-H1, SD-M4 |
| Concurrency correctness | ★★★★★ | Async + threadpool for sync drivers |
| Concurrency capacity | ★★★☆☆ | Bounded by threadpool/pool sizing (SD-M5) |
| Caching strategy | ★★★★☆ | Multi-level; needs TTL/invalidation (SD-M3) |
| Resilience / fault tolerance | ★★★☆☆ | Good retries/fail-closed; no breaker (SD-H2) |
| State & consistency | ★★★★☆ | Checkpointer + store; persistence-on-disconnect gap (SD-M2) |
| Data modeling | ★★★★★ | Stable IDs, hybrid indexes, verified ingestion |
| Deployment topology | ★★★☆☆ | Agent runtime + startup DDL to resolve (SD-H3, SD-M6) |
| Observability | ★★★★☆ | Logs + traces; add metrics (SD-L4) |

---

## 4. Prioritized action list (design)

| # | Action | Severity | Effort |
|---|--------|----------|--------|
| 1 | Bound/sample/paginate the full-graph endpoint (SD-H1) | High | M |
| 2 | Add circuit breakers + fast-fail for OpenAI/LightRAG (SD-H2) | High | M |
| 3 | Settle agent deployment topology + tighten CORS (SD-H3) | High | S–M |
| 4 | Distributed rate limiting via Redis/gateway (SD-M1) | Medium | S–M |
| 5 | Durable assistant-turn persistence (post-response job) (SD-M2) | Medium | M |
| 6 | Cache TTL/invalidation on schema + full graph (SD-M3) | Medium | S |
| 7 | Paginate message + conversation reads (SD-M4, SD-L1) | Medium | S |
| 8 | Deliberate threadpool/DB-pool sizing + docs (SD-M5) | Medium | S |
| 9 | One-off migration/setup job instead of per-replica DDL (SD-M6) | Medium | S |
| 10 | Metrics, SSE heartbeat, idempotency key, token-based budget (SD-L2…L5) | Low | S |

---

## 5. Summary

The **macro design is sound**: a stateless, horizontally-scalable app tier over durable stores, a genuine hybrid GraphRAG pipeline, path-appropriate resilience (fail-closed answers, fail-open enhancements), and clean layered boundaries. There are **no critical design flaws**. The High items are scale/resilience refinements (bound the full-graph payload, add circuit breakers, finalize the agent runtime); the Medium items harden distributed behavior (shared rate limiting, durable persistence, cache freshness, pagination, capacity sizing, startup coordination). Addressing the three High items materially improves behavior under load and dependency failure.
