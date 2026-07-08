# nalm-ai-agents — QA / Code Review Report

**Reviewer:** Automated QA pass
**Date:** 2026-04-09
**Scope:** Full repo (`apps/agents`, `apps/frontend`, `gas-scripts/`, infra) — security, code quality, AI agent design, documentation, repo structure.

---

## 1. Executive Summary

`nalm-ai-agents` is a monorepo hosting two LangGraph-based agents (PO Parser, Image Tagger) behind a unified FastAPI service, with a Next.js dashboard and a Google Apps Script submodule for Gmail/Drive triggers. The fundamentals are good — clean separation between graph nodes, shared service clients, Docker Compose orchestration, and an extensive root README.

However, the project is **not production-ready**. The most pressing problems are:

1. **Public, unauthenticated APIs** with permissive CORS exposing all stored data.
2. **No LangGraph checkpointer or store** — agents have zero memory, zero resumability, and cannot improve from user corrections.
3. **No human-in-the-loop gate** before high-stakes Airtable writes on PO data.
4. **God files** (`api/main.py` ≈ 580 LOC, `extract_po.py` ≈ 360 LOC) mixing transport, business logic, and persistence.

### Findings counts

| Severity | Security | Code Quality | AI Agent | Total |
|----------|----------|--------------|----------|-------|
| Severe   | 3        | 0            | 3        | **6** |
| High     | 6        | 5            | 3        | **14** |
| Medium   | 5        | 4            | 3        | **12** |
| Low      | 2        | 3            | 1        | **6**  |

---

## 2. Repository Overview

### Layout
```
nalm-ai-agents/
├── apps/
│   ├── agents/          # Python — FastAPI + LangGraph (PO Parser, Image Tagger)
│   │   ├── src/
│   │   │   ├── api/main.py             # Unified FastAPI app (~580 LOC)
│   │   │   ├── po_parser/              # 5-node LangGraph DAG
│   │   │   ├── image_tagging/          # parallel taggers + vision
│   │   │   └── services/               # OpenAI, Airtable, Supabase, GAS clients
│   │   ├── Dockerfile
│   │   ├── langgraph.json
│   │   └── requirements.txt
│   └── frontend/        # Next.js 16 / React 19 dashboard
├── gas-scripts/         # Git submodule — Google Apps Script triggers + WebApp
├── description/         # Project briefs + sample POs
├── scripts/             # E2E mock test
├── docker-compose.yml
├── .env.example
└── README.md
```

### Tech stack
- **Backend:** Python 3.11, FastAPI, LangGraph 0.2+, LangChain-OpenAI, OpenAI gpt-4o / gpt-4o-mini, pyairtable, psycopg2 (Supabase), pdfplumber, PyMuPDF, Pydantic v2.
- **Frontend:** Next.js 16, React 19, Tailwind 4, shadcn/base-ui.
- **Infra:** Docker Compose (agents :8000, frontend :3000, optional mock test profile).
- **Glue:** Google Apps Script (Gmail/Drive triggers + Sheets writer + WebApp router).

### Components
- **PO Parser** — `classify → extract_po → validate → write_airtable → callback_gas`. Triggered by `/webhook/email` from GAS.
- **Image Tagger** — preprocess → parallel taggers → vision analyzer → DB write. Triggered by `/api/analyze-image`, `/api/bulk-upload`, `/webhook/drive-image`.
- **Frontend** — browse/search tagged images via FastAPI.
- **GAS submodule** — `EmailTrigger.js` (PO scan, 5-min), `DriveTrigger.js` (image scan, 5-min), `WebApp.js` (callback router).

---

## 3. Security Findings

### 🔴 Severe

**S1. Open CORS with credentials** — `apps/agents` `src/api/main.py:114` (historical layout)
```python
CORSMiddleware(allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```
Wildcard origin combined with `allow_credentials=True` allows any site to issue authenticated cross-origin requests against this API. Browsers actually reject `*` + credentials, but the intent is wrong and the moment a real origin is whitelisted in addition, the API becomes a CSRF vector. **Fix:** explicit origin allowlist; never combine `*` with credentials.

**S2. Unauthenticated image data APIs** — `main.py:265-279`, `282-294`, `320-346`, `349-373`
- `GET /api/tag-image/{image_id}` — fetches any image's tags by ID
- `GET /api/tag-images` — lists all stored images
- `GET /api/search-images` — searches the entire catalog
- `GET /api/available-filters` — leaks the full taxonomy

No `Depends(verify_secret)` on any of these. UUID enumeration is feasible. **Fix:** require an auth dependency (API key, JWT, or signed session) on every non-public route.

**S3. GAS Web App exposed `ANYONE_ANONYMOUS` with broad scopes** — `gas-scripts/appsscript.json:8-19`
```json
"webapp":   { "executeAs": "USER_DEPLOYING", "access": "ANYONE_ANONYMOUS" },
"oauthScopes": [
  "gmail.readonly", "gmail.modify", "gmail.labels", "gmail.send",
  "drive.readonly", "script.external_request"
]
```
Anyone with the deployment URL can `doPost` and trigger code that runs **as the deploying user**, with `gmail.send` available. The webhook secret check (`Config.gs`) is the only barrier. **Fix:** drop `gmail.send` if not strictly needed; rotate the secret; consider switching to `USER_ACCESSING` or restricting the deployment to a Workspace domain.

### 🟠 High

**H1. Missing upload size limits** — `main.py:179-191`, `444-451`
`/api/analyze-image` and `/api/bulk-upload` accept `UploadFile` with no `max_size` enforcement. Trivial DoS via multi-GB upload. **Fix:** enforce `request.headers["content-length"]` limit + stream-and-cap during read.

**H2. Weak file validation** — `main.py:179-185`, `481-501`
- Suffix-only check (`.jpg`/`.png`) — bypassable as `shell.sh.jpg`.
- `/webhook/drive-image` does `base64.b64decode(image_b64)` with no size cap → OOM vector.
- Falls back to `.jpg` if suffix missing — silently accepts unknown content.
- No magic-number / `python-magic` verification.

**H3. Base64 decode without validation or size cap** — `apps/agents/src/po_parser/tools/file_helpers.py:12`
```python
return base64.b64decode(data_base64, validate=False)
```
`validate=False` swallows malformed input; no upper bound on decoded size. Multi-GB payload → OOM.

**H4. Unbounded SQL `limit` from user input** — `apps/agents/src/services/supabase/client.py:152-155`, called from `main.py:330`
`limit: int = 50` query param flows directly into the SQL `LIMIT` clause with no upper bound. Attacker passes `limit=99999999` → full-table scan. **Fix:** clamp server-side (`min(limit, 200)`).

**H5. Unbounded in-memory `BATCH_STORAGE`** — `main.py:39`, `454`
```python
BATCH_STORAGE: dict[str, dict] = {}
```
No TTL, no size cap, no cleanup. Repeated `/api/bulk-upload` calls leak memory until OOM. **Fix:** Redis with TTL, or LangGraph checkpointer (see §5).

**H6. Non-timing-safe secret comparison** — `main.py:486-488`
```python
secret = body.get("secret") or request.headers.get("x-webhook-secret", "")
if not secret or secret != expected:
```
Other endpoints correctly use `hmac.compare_digest`; this one doesn't. Theoretical timing-attack vector. **Fix:** use `hmac.compare_digest` everywhere a secret is compared.

### 🟡 Medium

**M1. Loose dependency pinning** — `apps/agents/requirements.txt`
All deps are `>=` with no upper bound and no lockfile. A surprise major-version bump can break or weaken security. **Fix:** generate `requirements.lock` (pip-tools / uv) and pin exact versions.

**M2. Error detail leak in global exception handler** — `main.py:103-109`
```python
return JSONResponse(status_code=500, content={"detail": str(exc), "type": type(exc).__name__})
```
Returns raw exception strings (file paths, DB errors, stack hints) to clients. **Fix:** log internally, return generic 500.

**M3. Container runs as root** — `apps/agents/Dockerfile`
`FROM python:3.11-slim` with no `USER` directive. Frontend Dockerfile correctly drops to `nextjs`. **Fix:** create a non-root user and `USER` it.

**M4. Batch IDs use `uuid4` instead of `secrets.token_urlsafe`** — `main.py:452`
`uuid4` is random but not a cryptographic secret. Since `/api/bulk-status/{batch_id}` is unauthenticated, batch IDs *are* the access token. **Fix:** `secrets.token_urlsafe(32)`.

**M5. No rate limiting** — anywhere
Combined with unauthenticated endpoints, this is a free amplification target.

### 🟢 Low

**L1. Placeholder secrets in `.env.example`** — `.env.example:8-9`
`change-me-webhook` / `change-me-gas-callback`. README should mandate rotation; consider a startup check that refuses to boot with placeholders.

**L2. No HTTPS enforcement** — `.env.example:45-52`
Defaults to `http://`. No HSTS or redirect middleware. Fine for dev, must be enforced in prod.

---

## 4. Code Quality / Refactor Findings

### 🟠 High

**Q2. God files**
- `apps/agents` `src/api/main.py` (~580 LOC, historical) — HTTP routing + URL rewriting + image processing + DB persistence + graph orchestration in one module.
- `apps/agents/src/po_parser/nodes/extract_po.py` (~360 LOC) — HTML stripping + spreadsheet parsing + PDF rendering + LLM calls + normalization in one node.

**Fix:** split `main.py` into `api/routes/{po,images,health}.py` + `services/image_pipeline.py`. Split `extract_po.py` into `text_extractor.py`, `pdf_extractor.py`, `spreadsheet_extractor.py`, with the LLM call as a thin orchestrator.

**Q3. Tight coupling — services imported inside handlers**
`main.py:128, 198, 216, 268, 333, 397, 407, 514, 524, 541, 561` all perform lazy **src.services.*** imports inside the function body. This:
- Hides dependencies from the function signature.
- Makes mocking impossible without monkeypatching imports.
- Defeats FastAPI's `Depends`-based DI.

**Fix:** module-level imports + `Depends(get_supabase_client)`-style injection.

**Q4. Copy-paste duplication**
Same Supabase save block repeated 4× in `main.py` (lines 214-231, 406-417, 523-536, plus `_run_bulk_batch`):
```python
if SUPABASE_ENABLED:
    client = get_client()
    if client:
        client.upsert_tag_record(...)
```
Same `_parse_filter_params` pattern repeated across 3 endpoints (`main.py:297-373`). **Fix:** one helper, one decorator, or push into the repository layer.

**Q5. Async hazards**
- `main.py:437-441` — fire-and-forget `asyncio.create_task(_run_bulk_batch(...))` with no timeout, no error propagation, no shutdown handling. If the process restarts mid-batch, the work is silently lost (BATCH_STORAGE is in-memory).
- `Request` object captured in a closure passed to a background task — its lifetime ends when the response is sent; reading `.headers` later is undefined behavior.

**Fix:** structured concurrency (`asyncio.TaskGroup`), persist batch state outside the request lifecycle, never reference `Request` after the handler returns.

**Q6. Broad exception handling**
- `main.py:103-109` — global `Exception` catch returns raw error.
- `main.py:197-200, 209-212` — bare `except Exception` swallows graph load errors.
- `extract_po.py:349` — bare `except Exception` returns `None`, validator continues with degraded state, pipeline writes a partial PO to Airtable.

**Fix:** catch concrete exceptions; for unexpected ones, log and **fail closed** (do not write).

### 🟡 Medium

**Q7. Magic numbers / strings**
- `image_tagging/nodes/taggers.py:68-71` — `confidence > 0.5` hardcoded.
- `po_parser/nodes/extract_po.py:40-48` — 7 date formats hardcoded.
- `main.py:36-37` — `ALLOWED_IMAGE_EXTENSIONS` / `ALLOWED_CONTENT_TYPES` defined inline.

**Fix:** centralize in a `config.py` exposed via Pydantic Settings.

**Q8. Configuration scattered**
`po_parser/settings.py`, `image_tagging/settings.py`, `image_tagging/configuration.py`, `services/*/settings.py`, plus 14+ ad-hoc `os.getenv` calls. **Fix:** one root `Settings` model with nested submodels.

**Q9. Type-hint coverage incomplete**
- `main.py:104` exception handler — `exc` untyped.
- `main.py:92` `_rewrite_tag_row(row: dict) -> dict` — should be a `TypedDict`.
- `image_tagging/nodes/taggers.py:40` returns `dict[str, Any]` — replace with concrete `TaggerResult` schema.

**Q10. Mixed concerns inside endpoints**
`main.py:179-262` (`analyze_image`) does upload validation + file I/O + graph invocation + DB persistence + response shaping in one function. **Fix:** thin handler → service object.

### 🟢 Low

**Q11. Dead code** — `apps/agents/src/po_parser/utils.py:6-9` defines `clamp_text()` which is never imported.

**Q12. Inconsistent naming** — both `settings.py` and `configuration.py` exist for image tagging.

**Q13. Frontend** — solid TypeScript types in `lib/types.ts` and `lib/constants.ts`; good baseline. Could benefit from API client abstraction instead of `fetch` calls scattered through components.

---

## 5. AI Agent Design Findings (LangGraph)

This is the biggest gap in the project, and the one with the highest leverage. The agents work, but they have **none of the LangGraph features that make agentic systems robust, observable, or improvable over time**.

### 🔴 Severe

**A1. No checkpointer on either graph** — `apps/agents/src/po_parser/graph_builder.py:34`, `apps/agents/src/image_tagging/graph_builder.py:37`
Both graphs call `.compile()` with no `checkpointer=` argument. Consequences:
- **No resumability.** If the Airtable write fails after the LLM extract, the entire 3-5-call pipeline must restart. Tokens and money wasted.
- **No time-travel debugging.** Can't replay a graph from any node in LangGraph Studio.
- **No human-in-the-loop.** `interrupt()` requires a checkpointer.
- **No durable state.** Process restart = lost runs.

**Fix:** wire `PostgresSaver` (Supabase Postgres is already in the stack) and pass a `thread_id` per inbound webhook (`message_id` for PO, `image_hash` for tagging).

```python
from langgraph.checkpoint.postgres import PostgresSaver
checkpointer = PostgresSaver.from_conn_string(settings.supabase_db_url)
graph = builder.compile(checkpointer=checkpointer)
```

**A2. No `BaseStore` — agent has no memory and cannot learn** — *(no file: feature is entirely missing)*
There is no `InMemoryStore`, `PostgresStore`, or any other LangGraph `BaseStore` configured. This is the user's headline concern, and it's correct:

- The agent **cannot remember user preferences** (e.g., "this customer always uses metric units", "this supplier puts the PO number in the subject line").
- The agent **cannot learn from corrections.** When a user manually fixes a misclassified PO line item in Airtable, the next email from the same supplier will repeat the same mistake.
- There is **no shared knowledge across runs** — every email/image is processed from a cold start.
- This is the difference between a *stateless extractor* and an *agent that gets better with experience*. Today this project is the former.

**Fix:** add a `PostgresStore` (or `InMemoryStore` for dev) and wire it into `.compile(store=...)`. Then:
1. Add a "memory recall" node at the start of the PO graph that retrieves prior corrections for the (sender, customer) pair via `store.search(("po_corrections", sender_email))`.
2. Inject those corrections into the extraction prompt as few-shot examples.
3. Add a webhook from Airtable (or a periodic diff job) that writes user corrections back via `store.put(("po_corrections", sender_email), key, correction)`.
4. For image tagging, key feedback by `(category, image_phash)` so similar images inherit corrections.

This single change is what turns the system from "an extractor" into "an agent that gets better with use."

**A3. No human-in-the-loop gate before Airtable writes** — `apps/agents/src/po_parser/nodes/airtable_writer.py:26-108`
The PO writer pushes records straight to Airtable. Status is hardcoded `"Needs Review"` (line 57), but the graph **never pauses** for human review — the record is already written. For a financial document workflow, this is the wrong default.

**Fix:** add an `interrupt()` after the validator node. The graph pauses, the API returns the proposed record + a `thread_id`, the user approves in the dashboard, and a `Command(resume=...)` continues the graph into the writer. Requires A1 (checkpointer).

### 🟠 High

**A4. No node-level retry policy** — only one rate-limit retry in `apps/agents/src/services/openai/client.py:72-78`
A single `RateLimitError` triggers a 2-second sleep + retry. Any other failure (timeout, 5xx, malformed response) crashes the node, which crashes the whole graph (no checkpoint to resume from). **Fix:** `add_node(name, fn, retry_policy=RetryPolicy(max_attempts=3, backoff_factor=2.0, retry_on=(APIError, TimeoutError)))`.

**A5. No streaming to the frontend** — `main.py:143`
Endpoints call `graph.invoke()` / `graph.ainvoke()` and return the final state. The user sees a 30-second hang. LangGraph's `astream_events` would let the dashboard show "Classifying… Extracting… Validating… Writing…" in real time. **Fix:** switch the long endpoints to SSE (`StreamingResponse`) over `astream_events`.

**A6. Silent error bubbling** — `extract_po.py:349-362`
`except Exception` → append to `errors[]` → return `None`. The validator (`validator.py:36`) sees `None`, logs a warning, and the writer still produces a record. End result: corrupted/empty POs land in Airtable as "Needs Review" with no extracted data. **Fix:** classify errors as recoverable vs fatal; route fatal errors to an error-terminal node that does **not** call the writer.

### 🟡 Medium

**A7. LangSmith only half-wired** — `services/openai/client.py:17-23`
Tracing is enabled if `LANGCHAIN_TRACING_V2=true`, but no `run_name`, `tags`, or `metadata` are set on graph runs. In LangSmith you can't filter "all PO extractions for customer X" or "all failed image taggings". **Fix:** wrap each invocation with `RunnableConfig(run_name=..., tags=[...], metadata={"customer_id": ...})`.

**A8. Mixed models, no fallback chain, no token budget** — `services/openai/settings.py:13-18`
- `gpt-4o` for vision extraction, `gpt-4o-mini` for classification — fine, but no fallback if the primary is unavailable.
- No `max_completion_tokens` budget on any call → unbounded cost on a runaway response.
- **Fix:** model fallback list, hard token caps, per-customer cost tracking.

**A9. Prompts as inline Python strings** — `apps/agents/src/po_parser/prompts/extraction.py`, `classification.py`
- No version field, no metadata, no `git blame` story.
- A/B testing or rollback requires editing source and redeploying.
- **Fix:** move to LangSmith Prompt Hub *or* `.yaml`/`.j2` files with a `version` field, loaded by a small `PromptRegistry`.

### 🟢 Low

**A11. No cross-image learning** — `image_tagging/schemas/states.py:6-20`
`partial_tags` uses an `Annotated[..., operator.add]` reducer that only accumulates within one image's run. No cross-image feedback loop. **Fix:** combine with A2 — keyed feedback in the store.

### ✅ What's good in the agent design

- **Pure node-based graphs** (no `create_react_agent`) is the **right** call for these deterministic pipelines. Don't change this.
- Clean separation of `nodes/`, `schemas/`, `prompts/`, `tools/` inside each agent.
- LangGraph Studio integration via `langgraph.json` is set up correctly.
- Pydantic-based structured outputs in extraction.

---

## 6. Architecture / Design Pattern Recommendations

| Pattern | Where to apply | Why |
|---------|----------------|-----|
| **Service layer** | Pull image-pipeline + PO-pipeline orchestration out of `main.py` into `services/image_pipeline.py` and `services/po_pipeline.py` | Lets you test without spinning up FastAPI |
| **Repository pattern** | `services/supabase/client.py`, `services/airtable/client.py` | Makes DB swappable; cleaner separation |
| **Dependency injection (`Depends`)** | All endpoint handlers in `main.py` | Replaces in-handler imports; trivial mocking |
| **Single Settings object** | Replace per-module settings with one root `Settings(BaseSettings)` with nested sub-models | One source of truth; one place to validate env at startup |
| **Checkpointer + Store** | Both LangGraph builders | Resumability, memory, human-in-the-loop (see §5) |
| **Structured concurrency (`asyncio.TaskGroup`)** | `_run_bulk_batch` in `main.py:437` | Replaces fire-and-forget; gives error propagation |
| **Strategy pattern** | `extract_po.py` text/PDF/spreadsheet branches | Replace inline `if`-tree with extractor strategies registered by content type |

---

## 7. Tooling Gaps

| Gap | Impact | Recommendation |
|-----|--------|----------------|
| No linter / formatter | Style drift | `ruff` + `ruff format` (replaces black + isort + flake8); `eslint` already configured for frontend but not enforced |
| No pre-commit hooks | Bad code lands in main | `pre-commit` with ruff, ruff-format, end-of-file-fixer, check-yaml |
| No CI | No automated gate | GitHub Actions: lint → typecheck on every PR |
| No type checker | `mypy`/`pyright` would catch many of the dict/Any issues | Add `pyright` in CI |

**Update (2026-04):** The monorepo restructure (`docs/description/MONOREPO_RESTRUCTURE_PLAN.md`) added **ruff**, **pre-commit**, **GitHub Actions CI**, and **pyright** at the repo root, addressing all four gaps above. Dependency pinning is now via **uv** + **uv.lock** (addresses **M1**). The backend Docker image runs as a **non-root** user (addresses **M3**).

---

## 8. Documentation Gaps

| What | Where | Priority |
|------|-------|----------|
| Per-app READMEs | `apps/agents/README.md` (missing); `apps/frontend/README.md` (default Next.js stub) | High |
| Function docstrings on critical helpers | `_rewrite_uploads_url`, `_parse_filter_params`, `_norm_header`, all node functions | High |
| Module docstrings | Most node files in `po_parser/nodes/` and `image_tagging/nodes/` | Medium |
| `CONTRIBUTING.md` | Repo root | Medium |
| Deployment runbook | `docs/deployment.md` — env isolation, secret rotation, scaling | Medium |
| Prompt versioning / changelog | `apps/agents/src/po_parser/prompts/CHANGELOG.md` | Medium |
| `.env.example` field descriptions | Inline comments per variable explaining purpose + format | Low |
| OpenAPI/Swagger link in README | FastAPI auto-generates `/docs` — mention it | Low |

The root `README.md` is already strong (quick-start, env vars, endpoints, LangGraph Studio, submodule instructions). Don't rewrite it — augment it.

---

## 9. Repository Separation Recommendations

The user explicitly asked: "how to best separate the repos for best separation of concerns."

### Current state
- One repo, one `requirements.txt`, one Docker image for both agents.
- Both agents share `src/services/` (good).
- Both agents share `src/api/main.py` (bad — coupling on the HTTP boundary).
- `gas-scripts/` is already a git submodule (good).
- `apps/frontend/` is independent enough to live anywhere.

### Option A — **Recommended: enforce boundaries inside the monorepo**

Keep one repo (cheap dev loop, atomic cross-cutting changes), but:

```
nalm-ai-agents/
├── packages/
│   └── shared-services/         # promoted from apps/agents/src/services/
│       ├── pyproject.toml       # installable as `nalm-shared-services`
│       └── src/
├── apps/
│   ├── po-parser/               # was apps/agents/src/po_parser
│   │   ├── pyproject.toml       # depends on nalm-shared-services
│   │   ├── Dockerfile
│   │   └── src/
│   ├── image-tagger/            # was apps/agents/src/image_tagging
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── src/
│   └── frontend/                # unchanged
├── gas-scripts/                 # unchanged (submodule)
└── docker-compose.yml           # 4 services: po-parser, image-tagger, frontend, postgres
```

Benefits:
- Each agent gets its own deploy lifecycle, its own Dockerfile, its own dependency set, its own scaling profile.
- Shared services live in **one** package — no copy-paste.
- The unified `api/main.py` god file disappears: each agent owns its HTTP routes.
- `uv` or `pdm` workspaces handle the multi-package layout natively.

### Option B — Polyrepo split

Split into 5 repos:
- `nalm-shared-services` (Python library, published to internal index)
- `nalm-po-parser` (depends on shared-services)
- `nalm-image-tagger` (depends on shared-services)
- `nalm-frontend`
- `nalm-gas-scripts` (already a submodule, just promote it)

Use this only if the agents grow separate teams. Trade-offs: each cross-cutting change becomes 2-3 PRs across repos; CI overhead doubles; version-skew bugs become possible. Do not jump to this until Option A starts hurting.

### Recommendation
**Do Option A now**, in this order:
1. Extract `shared-services` into `packages/shared-services` with its own `pyproject.toml`.
2. Split `apps/agents` into `apps/po-parser` and `apps/image-tagger`, each importing `shared-services`.
3. Give each its own Dockerfile and `langgraph.json`.
4. Update `docker-compose.yml` to run them as separate services.
5. Re-evaluate Option B in ~6 months only if team boundaries demand it.

---

## 10. Prioritized Action List

Ordered by impact ÷ effort. The first three are blockers for any production deployment.

| # | Action | Severity | Effort | Section | Status (2026-04 restructure) |
|---|--------|----------|--------|---------|------------------------------|
| 1 | Add auth (`Depends`) + restrict CORS to known origins | Severe | S | S1, S2 | Open |
| 2 | Wire `PostgresSaver` checkpointer + `PostgresStore` for memory | Severe | M | A1, A2 | Open |
| 3 | Add `interrupt()` HITL gate before Airtable writes | Severe | M | A3 | Open |
| 4 | Enforce upload size limits + magic-number validation | High | S | H1, H2, H3 | Open |
| 5 | Replace in-memory `BATCH_STORAGE` with checkpointer-backed state | High | S | H5 | Open |
| 6 | Split `api/main.py` into routes + service layer; introduce DI | High | M | Q2, Q3, Q10 | Partially done: `main.py` moved to `apps/backend`; internal split + DI deferred |
| 7 | Add `RetryPolicy` to all graph nodes; switch to `astream_events` | High | S | A4, A5 | Open |
| 8 | Execute monorepo Option A (extract `shared-services`, split agents) | Medium | L | §9 | Done (conservative): `apps/agents` + `apps/backend` per `MONOREPO_RESTRUCTURE_PLAN.md` (both graphs stay in one agents package; differs from full §9 split) |

---

## Appendix: file:line index of every reference in this report

| File | Line(s) | Issue |
|------|---------|-------|
| `apps/agents` `src/api/main.py` | 36-37 | Magic constants (Q7) |
| | 39, 454 | Unbounded BATCH_STORAGE (H5, Q5) |
| | 92 | Missing TypedDict (Q9) |
| | 103-109 | Error leak + broad except (M2, Q6) |
| | 114 | Open CORS (S1) |
| | 128, 198, 216, 268, 333, 397, 407, 514, 524, 541, 561 | In-handler imports (Q3) |
| | 143 | No streaming (A5) |
| | 179-262 | Mixed concerns + weak validation (Q10, H1, H2) |
| | 197-200, 209-212 | Bare except (Q6) |
| | 214-231, 406-417, 523-536 | Copy-paste DB save (Q4) |
| | 265-373 | Unauthenticated image APIs (S2) |
| | 297-373 | Copy-paste filter parsing (Q4) |
| | 437-441 | Fire-and-forget asyncio.create_task (Q5) |
| | 444-501 | Bulk upload + drive webhook gaps (H1, H2) |
| | 452 | uuid4 batch IDs (M4) |
| | 486-488 | Non-timing-safe compare (H6) |
| `apps/agents/src/po_parser/graph_builder.py` | 34 | No checkpointer (A1) |
| `apps/agents/src/po_parser/nodes/airtable_writer.py` | 26-108 | No HITL gate (A3) |
| `apps/agents/src/po_parser/nodes/extract_po.py` | 1-362 | God file (Q2) |
| | 40-48 | Hardcoded date formats (Q7) |
| | 349-362 | Bare except / silent fail (Q6, A6) |
| `apps/agents/src/po_parser/prompts/extraction.py` | 1-36 | Inline prompts (A9) |
| `apps/agents/src/po_parser/tools/file_helpers.py` | 12 | base64 OOM (H3) |
| `apps/agents/src/po_parser/utils.py` | 6-9 | Dead code (Q11) |
| `apps/agents/src/image_tagging/graph_builder.py` | 37 | No checkpointer (A1) |
| `apps/agents/src/image_tagging/nodes/taggers.py` | 40, 68-71 | Type hints + magic threshold (Q9, Q7) |
| `apps/agents/src/image_tagging/schemas/states.py` | 6-20 | No cross-image memory (A11) |
| `apps/agents/src/services/openai/client.py` | 17-23 | Half-wired LangSmith (A7) |
| | 72-78 | Single retry only (A4) |
| `apps/agents/src/services/openai/settings.py` | 13-18 | Mixed models, no fallback (A8) |
| `apps/agents/src/services/supabase/client.py` | 152-155 | Unbounded SQL limit (H4) |
| `apps/agents/Dockerfile` | — | Root user (M3) |
| `apps/agents/requirements.txt` | — | Loose pinning (M1) |
| `gas-scripts/appsscript.json` | 8-19 | ANYONE_ANONYMOUS + broad scopes (S3) |
| `.env.example` | 8-9 | Placeholder secrets (L1) |
| | 45-52 | No HTTPS (L2) |

---

*End of report.*
