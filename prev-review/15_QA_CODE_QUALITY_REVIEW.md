# QA Code Quality, Design & Optimization Review — `apps/agents` and `apps/backend`

**Date:** 2026-04-20
**Reviewer:** QA / Code Quality
**Scope:** Engineering craft of `apps/agents/` and `apps/backend/`. Security findings are tracked separately in `14_QA_SECURITY_REVIEW.md` — this document deliberately avoids restating them.

---

## Executive summary

The codebase is reasonably small (~2.5k LOC in scope), well-organised at the package level, and the LangGraph wiring is clean. Most issues are **leverage opportunities**, not bugs: the same patterns are reinvented per-node, abstractions leak in a few places, and several easy wins are left on the table for performance and developer ergonomics.

**The five highest-leverage refactors:**

1. **Collapse the 8 tagger wrapper functions** in `image_tagging/nodes/taggers.py` into a config table + factory. Removes ~65 lines of boilerplate and makes adding a new tagger one line.
2. **Stop constructing `ChatOpenAI` on every call** in `run_tagger` (`taggers.py:54`) and `vision_analyzer` (`vision.py:49`). One `lru_cache`'d factory keyed on model name. Significant cost in per-image latency today.
3. **Parallelise `/api/bulk-upload`** (`apps/backend/src/api/routes/bulk.py:78-85`). The handler is `async` but the loop is `for ... await ...`. Wrap in `asyncio.gather` with a `Semaphore` and you get N× throughput basically for free.
4. **Move `BATCH_STORAGE` out of `api/config.py`** and out of process. A mutable dict in a config module is a smell; under multi-worker deploys it returns 404 non-deterministically.
5. **Extract a single `nodes/_clients.py` module in `po_parser/nodes/`** to hold the OpenAI / Airtable / GAS singletons. The same `_client()` lazy-init pattern is copy-pasted across 5 node files.

Issue counts (after de-duping subagent findings and verifying against source):

| Severity | Count |
|----------|-------|
| High     | 12 |
| Medium   | 18 |
| Low / Info | 11 |
| **Total** | **41** |

---

## Findings — `apps/agents/`

### CODE QUALITY

#### A-Q1. `_client()` lazy-init pattern is copy-pasted across 5 node files
- **Severity:** High
- **Location:**
  - `apps/agents/src/agents/po_parser/nodes/classifier.py:18-25` (OpenAI)
  - `apps/agents/src/agents/po_parser/nodes/extract_po.py:26-55` (OpenAI)
  - `apps/agents/src/agents/po_parser/nodes/validator.py:16-23` (OpenAI + Airtable)
  - `apps/agents/src/agents/po_parser/nodes/airtable_writer.py:16-23` (Airtable)
  - `apps/agents/src/agents/po_parser/nodes/gas_callback.py:15-22` (GAS)
- **Issue:** Each module declares its own `_X: Client | None = None` plus a private `_client()` accessor. Same shape, five times.
- **Impact:** Five places to update when you want retries, metrics, or a thread-safe init. Multiple `AirtableClient()` instances are constructed across nodes — each instantiates pyairtable, rebuilds table-id maps, etc.
- **Fix:** Create `apps/agents/src/agents/po_parser/nodes/_clients.py`:
  ```python
  from functools import lru_cache
  from services.airtable import AirtableClient
  from services.gas_callback import GASCallbackClient
  from services.openai import OpenAIClient

  @lru_cache(maxsize=1)
  def openai() -> OpenAIClient: return OpenAIClient()
  @lru_cache(maxsize=1)
  def airtable() -> AirtableClient: return AirtableClient()
  @lru_cache(maxsize=1)
  def gas() -> GASCallbackClient: return GASCallbackClient()
  ```
  Then nodes import `from ._clients import openai`. `lru_cache` is thread-safe and removes the dance entirely.

#### A-Q2. The 8 tagger functions are near-identical wrappers
- **Severity:** High
- **Location:** `apps/agents/src/agents/image_tagging/nodes/taggers.py:100-187`
- **Issue:** `tag_season`, `tag_theme`, … `tag_product` each call `await run_tagger(state, "<category>", instructions=..., max_tags=...)`. 65 lines of boilerplate plus two parallel registries (`TAGGER_NODE_NAMES` and `ALL_TAGGERS`) that must be kept in sync with `taxonomy.py` and `configuration.py` by hand.
- **Impact:** Adding a tagger requires touching 4 places. Drift risk between the registry list and the dict.
- **Fix:** Single source of truth + factory:
  ```python
  TAGGER_SPECS: list[TaggerSpec] = [
      TaggerSpec("season_tagger",   "season",          None,                                          None),
      TaggerSpec("theme_tagger",    "theme",           "Select all aesthetic themes that apply.",     None),
      TaggerSpec("objects_tagger",  "objects",         "Select all visible objects…",                 MAX_OBJECTS),
      TaggerSpec("color_tagger",    "dominant_colors", "Select up to 5 dominant colors…",             MAX_COLORS),
      TaggerSpec("design_tagger",   "design_elements", "Select all applicable patterns…",             None),
      TaggerSpec("occasion_tagger", "occasion",        "Select all applicable occasions…",            None),
      TaggerSpec("mood_tagger",     "mood",            "Select all applicable moods…",                None),
      TaggerSpec("product_tagger",  "product_type",    "Select the single most likely product type…", 1),
  ]

  def make_tagger(spec: TaggerSpec):
      async def _tag(state):
          return await run_tagger(state, spec.category, spec.instructions, spec.max_tags)
      _tag.__name__ = spec.node_name
      return _tag

  ALL_TAGGERS = {s.node_name: make_tagger(s) for s in TAGGER_SPECS}
  TAGGER_NODE_NAMES = list(ALL_TAGGERS)
  ```
  Bonus: kills the lazy `from ..configuration import MAX_OBJECTS` imports inside the per-tagger functions.

#### A-Q3. `extract_po_node` has too many responsibilities
- **Severity:** High
- **Location:** `apps/agents/src/agents/po_parser/nodes/extract_po.py` (entire file, ~363 LOC; `extract_po_node` is the orchestrator at the bottom)
- **Issue:** One module owns: HTML cleaning, header alias normalisation, date parsing, currency parsing, xlsx/csv parsing, PDF→image rendering, multimodal LLM orchestration with retry, and JSON normalisation. 16 private helpers in one file.
- **Impact:** The deterministic helpers (`_normalize`, `_clean_body`, `_parse_date`, `_HEADER_ALIASES`) are highly testable but currently coupled to the LLM-calling node. Refactors are risky because the file is dense.
- **Fix:** Split into:
  - `extract_po/normalize.py` — pure functions (`_normalize`, `_clean_body`, header/date/currency utils, constants)
  - `extract_po/parsing.py` — file readers (xlsx/csv/pdf)
  - `extract_po/node.py` — the LangGraph node (LLM call + glue)
  Each piece becomes independently testable.

#### A-Q4. Inconsistent error-append patterns across PO-parser nodes
- **Severity:** Medium
- **Location:**
  - `apps/agents/src/agents/po_parser/nodes/classifier.py:74-79` (mutates `state["errors"]`, returns state)
  - `apps/agents/src/agents/po_parser/nodes/extract_po.py:318-319` (returns `{"errors": [...]}` — replaces, doesn't append)
  - `apps/agents/src/agents/po_parser/nodes/airtable_writer.py:37-38` (local `errs` list, returns `{"errors": errs}`)
  - `apps/agents/src/agents/po_parser/nodes/gas_callback.py:79` (`logger.exception` only, no state update)
- **Issue:** Three different conventions for accumulating errors in state. Without an `operator.add` reducer on `errors`, returning `{"errors": [...]}` overwrites prior errors silently.
- **Fix:** Pick one. Easiest: add `errors: Annotated[list[str], operator.add]` to `AgentState` and always return `{"errors": [<short_label>]}` from nodes. Use a small helper:
  ```python
  def err(label: str, exc: Exception | None = None) -> dict:
      logger.exception(label) if exc else logger.error(label)
      return {"errors": [label]}
  ```
  Document this in `nodes/README.md`.

#### A-Q5. `Optional` and `X | None` are mixed within the same file
- **Severity:** Low
- **Location:** `apps/agents/src/services/airtable/client.py:4` imports `Optional` but uses `X | None` at line 106.
- **Fix:** Project-wide: standardise on `X | None` (PEP 604; Python 3.11+). Add `ruff` rule `UP007`.

#### A-Q6. `_HEADER_ALIASES` and `_DATE_FORMATS` are buried in a node file
- **Severity:** Low
- **Location:** `apps/agents/src/agents/po_parser/nodes/extract_po.py:28-48`
- **Fix:** Move to `apps/agents/src/agents/po_parser/constants.py`. If you ever add an invoice parser, you'll thank yourself.

#### A-Q7. Loose dict typing across nodes
- **Severity:** Medium
- **Location:** Throughout `po_parser/nodes/*.py` and `image_tagging/nodes/*.py`
- **Issue:** Node return values are typed as `dict[str, Any]` or bare `dict`. State updates are stringly-typed (`{"errors": [...]}`, `{"partial_tags": [...]}`).
- **Impact:** Typos like `{"erorrs": [...]}` are not caught by mypy/pyright. Hard to refactor state schema.
- **Fix:** Either return narrowed `TypedDict`s (one per node) or use `pydantic.BaseModel` patches. Even `TypedDict("ClassifierUpdate", {"is_po": bool, "rationale": str})` improves IDE support enormously.

#### A-Q8. `_parse_tagger_response` strips Markdown fences by hand
- **Severity:** Low
- **Location:** `apps/agents/src/agents/image_tagging/nodes/taggers.py:16-34`
- **Issue:** Manual `split("\n")` + `startswith("```")` walk is fragile (e.g., trailing spaces).
- **Fix:** `re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)` or use the same helper proposed for `extract_po` JSON parsing.

#### A-Q9. Lazy imports inside hot paths
- **Severity:** Low
- **Location:** `apps/agents/src/agents/image_tagging/nodes/taggers.py:113, 124` (`from ..configuration import MAX_OBJECTS` / `MAX_COLORS` inside the per-tagger functions)
- **Fix:** Import once at module top. The "avoid circular import" reason no longer applies after the A-Q2 refactor.

#### A-Q10. Vague names: `it`, `t`, `out`, `data`
- **Severity:** Low
- **Location:** `apps/agents/src/agents/image_tagging/nodes/aggregator.py` (`t` for tags), `gas_callback.py:37-49` (`it` for items)
- **Fix:** `tag` and `item`. Trivial but improves grep-ability.

---

### DESIGN PATTERNS / ARCHITECTURE

#### A-D1. Two parallel LLM-client styles
- **Severity:** High
- **Location:**
  - PO parser: thin wrapper `services/openai/client.py` (`OpenAIClient`)
  - Image tagging: raw `langchain_openai.ChatOpenAI` constructed inside nodes (`taggers.py:54`, `vision.py:49`)
- **Issue:** Two ways to do the same thing. PO-parser side has token logging, retry shape, settings management. Image-tagging side has none of that and re-instantiates clients per call.
- **Impact:** Cross-cutting concerns (timeouts, cost telemetry, prompt caching, vendor swap) have to be implemented twice.
- **Fix:** Either (a) use `OpenAIClient` everywhere by adding an `ainvoke_chat(...)` method that returns text + token usage, or (b) standardise on `ChatOpenAI` everywhere and put one `LangchainLLMClient` wrapper around it. Pick one and delete the other.

#### A-D2. Validator reaches into Airtable's raw dict
- **Severity:** High
- **Location:** `apps/agents/src/agents/po_parser/nodes/validator.py:59-84`
- **Issue:** The node calls `at.find_po_by_number()` and then digs into `rec["id"]` and `rec["fields"]["Raw Extract JSON"]`. The literal field name "Raw Extract JSON" lives in the node, not in the service.
- **Impact:** A schema rename in Airtable breaks the node, not the service. Coupling violates the Dependency-Inversion principle: high-level policy (validation) shouldn't know low-level details (Airtable field names).
- **Fix:** Add `AirtableClient.find_po_duplicate(po_number) -> PODuplicateInfo | None` returning a typed object. Validator takes the typed thing and never sees raw dicts.

#### A-D3. Settings split across three files for image_tagging
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/{settings.py, configuration.py}` plus `services/openai/settings.py`
- **Issue:** `settings.py` reads `OPENAI_API_KEY`/`OPENAI_MODEL` via `os.getenv`. `configuration.py` holds confidence thresholds + max-tag caps. `OpenAISettings` (pydantic) lives in services.
- **Fix:** Single `pydantic_settings.BaseSettings` per agent (e.g. `ImageTaggingSettings`) with all knobs. One place to look, one place to override in tests.

#### A-D4. PostgresSaver checkpointer holds a single connection (not a pool)
- **Severity:** Medium
- **Location:** `apps/agents/src/services/checkpointer.py:64, 135` (`Connection.connect(...)` then `PostgresSaver(conn)`)
- **Issue:** The checkpointer wraps a single connection. Under concurrent graph runs (image tagging fans out 8 taggers in parallel), all checkpoint writes serialise on that one connection.
- **Fix:** Use `psycopg_pool.ConnectionPool` (sync) and `AsyncConnectionPool` (async). Both LangGraph savers accept a pool.

#### A-D5. State has no reducers on the dict-shaped fields
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/schemas/states.py` (`vision_raw_tags: dict`, `metadata: dict`, `flagged_tags: list`)
- **Issue:** `partial_tags` correctly uses `Annotated[list, operator.add]`, but the other dict/list fields have no reducers. On replay/retry, the latest write wins — which sometimes silently drops earlier flagged_tags entries.
- **Fix:** Add explicit reducers (`merge_dicts`, `operator.add`) per field. Document the expected merge semantics in `schemas/states.py`.

#### A-D6. `image_tagging/settings.py` raises at import time when key is missing
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/settings.py:11-13`
- **Issue:** Importing the package fails hard if `OPENAI_API_KEY` is unset, even when running `langgraph dev` to inspect the graph.
- **Fix:** Defer the check to first use (`raise RuntimeError(...)` inside the LLM call factory) or default to `""` and let the OpenAI SDK raise its own clearer error.

#### A-D7. Confidence thresholds and tag caps are hard-coded
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/configuration.py:5, 12-15`, `apps/agents/src/agents/po_parser/nodes/routing.py:8`
- **Fix:** Read from env via the consolidated settings module (A-D3). They will need tuning in prod.

#### A-D8. The async checkpointer module mixes sync and async lifecycles
- **Severity:** Medium
- **Location:** `apps/agents/src/services/checkpointer.py` (sync + async coexist)
- **Issue:** Two singleton dicts, two locks, two close functions. Easy to call the wrong one. Backend `lifespan` already correctly closes both, but the API surface invites mistakes.
- **Fix:** Either split into two modules (`checkpointer/sync.py`, `checkpointer/aio.py`) or hide both behind a `class Checkpointers` with a single `aclose_all()`.

---

### OPTIMIZATION

#### A-O1. `ChatOpenAI` instantiated per LLM call
- **Severity:** High
- **Location:** `apps/agents/src/agents/image_tagging/nodes/taggers.py:54`, `apps/agents/src/agents/image_tagging/nodes/vision.py:49`
- **Issue:** Every call to `run_tagger` constructs a fresh `ChatOpenAI`. With 8 taggers + 1 vision per image, that's 9 client constructions per image, each spinning up a new httpx connection pool.
- **Impact:** Wasted CPU; no HTTP keep-alive across calls in the same image; garbage collector pressure.
- **Fix:**
  ```python
  from functools import lru_cache
  @lru_cache(maxsize=4)
  def get_chat_openai(model: str) -> ChatOpenAI:
      return ChatOpenAI(model=model, api_key=OPENAI_API_KEY, max_tokens=1024, timeout=30)
  ```
  Then `llm = get_chat_openai(OPENAI_MODEL)` inside `run_tagger`/`vision_analyzer`.

#### A-O2. `taxonomy.get_flat_values()` rebuilds lists on every call
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/taxonomy.py:286-309` (called from `taggers.py:45` for every category, every image)
- **Issue:** Each call re-iterates the dict and concatenates child lists. For 8 taggers × N images, the same flat lists are rebuilt from scratch.
- **Fix:** `lru_cache` on the function, or precompute once at import:
  ```python
  _FLAT_VALUES: dict[str, list[str]] = {}
  for cat in TAXONOMY:
      _FLAT_VALUES[cat] = _compute_flat_values(cat)
  def get_flat_values(category: str) -> list[str]:
      return list(_FLAT_VALUES.get(category, ()))
  ```

#### A-O3. PO-parser nodes are sync; LLM calls block worker threads
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/po_parser/nodes/{classifier,extract_po,validator}.py`
- **Issue:** All PO-parser nodes are sync (`def`, not `async def`) and call `OpenAIClient().chat_completion(...)`. When the backend invokes the graph from an async route, LangGraph runs sync nodes in a thread-pool — fine for a single request, but it serialises CPU work and blocks one thread for the duration of each LLM call.
- **Fix:** Make the nodes `async def` and add `OpenAIClient.chat_completion_async(...)`. Eliminates the thread-pool detour and frees workers during the round-trip.

#### A-O4. Hand-rolled retry in image-tagging nodes
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/nodes/vision.py:60-67`, `taggers.py:56-63`
- **Issue:** `await asyncio.sleep(1 * (2**attempt))` with no jitter, no `Retry-After` honouring, no shared policy.
- **Fix:** Standardise on `tenacity` (already common in the ecosystem). Centralise the policy in one decorator and reuse.

#### A-O5. Validator double-serialises JSON for fingerprint comparison
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/po_parser/nodes/validator.py:66-75`
- **Issue:** Compares two POs with `json.dumps(prev, sort_keys=True) == json.dumps(snap, sort_keys=True)`. Both sides are dumped on every check.
- **Fix:** Hash once and store the hash on the Airtable record (or compare dicts directly: `prev == snap` is well-defined for dict-of-primitives).

#### A-O6. Prompt rebuilt + tokens re-sent for each tagger
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/nodes/taggers.py:53` and `prompts/tagger.py`
- **Issue:** Each tagger sends the full taxonomy slice for its category in the user message. The prompt template + style guidance is re-tokenised by OpenAI for every call.
- **Fix:** Move the static header to a `system` message and let OpenAI's prompt cache do the work (the system message + taxonomy slice should be cache-stable across calls in the same minute). Long term: investigate batching multiple categories into one call (8→2 calls).

#### A-O7. Image is base64-encoded twice for every request
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/nodes/preprocessor.py` (decodes the b64) and again indirectly in vision/tagger prompts that re-embed image data.
- **Issue:** The original bytes survive as `image_base64` in state; preprocessor decodes; downstream nodes ask for the raw bytes again. Worth profiling — for large images this can be the dominant cost.
- **Fix:** Decide which form is the source of truth (bytes or base64), not both.

#### A-O8. Heavy `image_base64` blob persisted in checkpointer state
- **Severity:** Medium
- **Location:** `apps/agents/src/agents/image_tagging/schemas/states.py` + `apps/backend/src/api/services/image_pipeline.py:38`
- **Issue:** The full base64 image is part of state and therefore checkpointed to Postgres on every node transition. For a 5 MB image that's ~7 MB of base64 written multiple times per run.
- **Fix:** Pass an `image_path` (or `image_url`) through state and read bytes from disk inside the preprocessor only. Or use a dedicated reducer that drops the blob after preprocessing.

#### A-O9. `services/checkpointer.py` does `import` inside locked critical sections
- **Severity:** Medium
- **Location:** `apps/agents/src/services/checkpointer.py:50-53, 121-124`
- **Issue:** `from langgraph.checkpoint.postgres import PostgresSaver` runs while `_state_lock` is held. Imports go through Python's import lock; nesting two locks during cold start invites hard-to-debug stalls.
- **Fix:** Move the imports to module top-level. They're cheap on subsequent calls anyway.

---

### TESTING & OBSERVABILITY

#### A-T1. No tests
- **Severity:** High
- **Location:** No `tests/` directory in `apps/agents/`
- **Highest-leverage targets:**
  - `extract_po._normalize` (pure function, dozens of date/currency edge cases)
  - `taxonomy.get_flat_values` / `get_parent_for_child`
  - `validator.validator_node` snapshot comparison
  - `_parse_tagger_response` markdown stripping
  - The full PO-parser graph against frozen fixtures using `MemorySaver` and a stub OpenAI client
- **Fix:** Add `pytest` to dev deps, drop a `tests/` folder, start with the four pure-function modules above. Stub external calls with `responses` (HTTP) and a fake `OpenAIClient`.

#### A-T2. No correlation ID across async fan-out
- **Severity:** Medium
- **Location:** `image_tagging/nodes/vision.py`, `taggers.py`
- **Issue:** Logs from 8 concurrent taggers for the same image are interleaved with logs from other concurrent images. No way to filter by `image_id`.
- **Fix:** Use `contextvars.ContextVar("image_id")` set at the top of `image_preprocessor`; configure `logging` formatter to include it.

#### A-T3. Token / latency / cost not recorded into state
- **Severity:** Medium
- **Location:** `services/openai/client.py` logs tokens but doesn't return them; `vision.py`/`taggers.py` don't measure either.
- **Fix:** Each LLM-calling node returns `{"llm_calls": [{"node": ..., "tokens_in": ..., "tokens_out": ..., "ms": ...}]}` reduced via `operator.add`. One field, full visibility.

#### A-T4. Logging-level discipline
- **Severity:** Low
- **Location:** Throughout
- **Issue:** Some failures are `warning`, others `error`, others `exception`. The Airtable duplicate-check failure (`validator.py:82`) is logged as `warning` even though it disables a critical safety check.
- **Fix:** Document level conventions in `apps/agents/README.md` (`error` = user-visible failure; `warning` = degraded but recoverable; `info` = lifecycle). Audit existing call sites against the policy.

---

## Findings — `apps/backend/`

### CODE QUALITY

#### B-Q1. `_parse_filter_params` is called with all 8 query args twice
- **Severity:** Medium
- **Location:** `apps/backend/src/api/routes/images.py:151-200` (`/search-images` and `/available-filters` both repeat the same 8 `name: str | None = None` params and pass them all through)
- **Issue:** Adding a 9th filter requires three edits: function signature, `/search-images` signature, `/available-filters` signature. Easy to miss one.
- **Fix:** Extract a `Depends`:
  ```python
  def filter_params(
      season: str | None = None, theme: str | None = None, ...
  ) -> dict[str, list[str]]:
      return _parse_filter_params(season=season, theme=theme, ...)

  @router.get("/search-images")
  def search_images(
      filters: Annotated[dict[str, list[str]], Depends(filter_params)],
      client: Annotated[SupabaseClient, Depends(get_supabase_client)],
      limit: int = Query(50, ge=1, le=200),
  ): ...
  ```

#### B-Q2. Routes return untyped `dict` — no `response_model` anywhere
- **Severity:** High
- **Location:** Every route in `apps/backend/src/api/routes/{images,bulk,drive_webhook,po_parser,health}.py`
- **Issue:** OpenAPI is incomplete; runtime response validation is off; refactors silently change the public contract.
- **Fix:** Define Pydantic response models per route (`AnalyzeImageResponse`, `TagImageRow`, `PaginatedTagImages`, `BulkAcceptedResponse`, `BulkStatusResponse`, `HealthResponse`). Pass `response_model=...`.

#### B-Q3. `analyze_image` does eight things
- **Severity:** Medium
- **Location:** `apps/backend/src/api/routes/images.py:59-127`
- **Issue:** The route validates extension/content-type, generates a UUID, reads the file, writes to disk, builds graph state, invokes the graph, persists to Supabase, reshapes tags into the response. 70 lines of mixed concerns.
- **Fix:** Move (read + persist + reshape) into `services/image_processing.py`:
  ```python
  class ImageProcessingService:
      async def analyze(self, file: UploadFile, request: Request) -> AnalyzeImageResponse: ...
  ```
  Route becomes a 5-line wrapper.

#### B-Q4. The `_normalize_tags` logic in `analyze_image` is a hidden helper
- **Severity:** Low
- **Location:** `apps/backend/src/api/routes/images.py:97-113`
- **Issue:** The `validated → tags_by_category` reshape is inline, repeated work-shape (the same data is also produced by `tag_aggregator` in the agent). Bulk and drive-webhook would have to repeat it if they ever returned tags.
- **Fix:** Extract `_tags_by_category(result: dict) -> dict[str, list[dict]]`. Or move it into the graph's aggregator so the API just passes the result through.

#### B-Q5. Inconsistent variable naming for filenames
- **Severity:** Low
- **Location:** `bulk.py:29` (`filename_orig`), `drive_webhook.py:44` (`filename_orig`), `images.py:65, 72` (`file.filename` then `filename`)
- **Fix:** `original_filename` for user input, `stored_filename` for what we wrote to disk. Be consistent.

#### B-Q6. Route handlers use `dict` instead of pydantic for webhook input
- **Severity:** Medium
- **Location:** `apps/backend/src/api/routes/drive_webhook.py:36-48` (`body = await request.json()` then `.get(...)` everywhere)
- **Issue:** PO-parser route uses a `IncomingEmail` Pydantic model (good); drive webhook does ad-hoc dict access. Inconsistent.
- **Fix:** Define `class DriveImageWebhookRequest(BaseModel)` and accept it as the body parameter. FastAPI handles validation and OpenAPI for free.

#### B-Q7. Vague names in route bodies
- **Severity:** Low
- **Location:** `images.py:115` (`out_url`), `bulk.py:117` (`out`), `drive_webhook.py:58` (`_process` — top-level helper hidden inside the route)
- **Fix:** `final_image_url`, `payload_copy`, `_process_drive_image`. Trivially better grep hits.

---

### DESIGN PATTERNS / ARCHITECTURE

#### B-D1. `BATCH_STORAGE` is mutable global state living inside `config.py`
- **Severity:** High
- **Location:** `apps/backend/src/api/config.py:22`, mutated from `apps/backend/src/api/routes/bulk.py:38, 43, 61, 73-75, 102-107, 119`
- **Issue:** Two problems in one place:
  1. Mutable runtime state in a module called `config.py`. Configuration ≠ state.
  2. In-process dict means `--workers > 1` returns 404 randomly when status hits a worker that didn't accept the upload.
- **Fix:** Move to `services/batch_store.py` (single-process, behind a lock) as a stop-gap; long-term back it with Redis or Postgres so multi-worker / restart works correctly.

#### B-D2. Late imports in `lifespan` hide a layering issue
- **Severity:** Medium
- **Location:** `apps/backend/src/api/main.py:30-35` (imports `services.checkpointer` and `services.supabase` inside `finally:`)
- **Issue:** The comment in the surrounding code makes it clear this is to avoid a circular import. That's a layering smell — `main.py` shouldn't be in any cycle with `services/`.
- **Fix:** Identify the cycle (likely `api.deps` → `agents` → `services` → ...) and break it at the top: `services/lifecycle.py` exposing `aclose_all()`. `main.py` imports it normally.

#### B-D3. `get_taxonomy` re-imports per request
- **Severity:** Low
- **Location:** `apps/backend/src/api/deps.py:98-101`
- **Issue:** `from agents.image_tagging.taxonomy import TAXONOMY` runs on every `/api/taxonomy` request. Python's import cache makes it cheap, but inconsistent with how graph singletons are cached in the same file.
- **Fix:** `@lru_cache(maxsize=1)` on `get_taxonomy`.

#### B-D4. Graphs are built lazily on first request
- **Severity:** Medium
- **Location:** `apps/backend/src/api/deps.py:27-72`
- **Issue:** `_ensure_image_graph` runs the first time `/api/analyze-image` is hit, including async checkpointer setup. The first request after deploy pays a multi-second cold-start.
- **Fix:** Build both graphs in `lifespan` startup and stash in `app.state`; deps just `return app.state.image_graph`. Fail fast on misconfiguration.

#### B-D5. `image_pipeline.py` is a junk-drawer module
- **Severity:** Medium
- **Location:** `apps/backend/src/api/services/image_pipeline.py`
- **Issue:** Mixes filesystem I/O (`save_image`), graph-state construction (`build_initial_state`), URL building (`image_url_for`), and DB persistence (`persist_to_supabase`). No coherent abstraction.
- **Fix:** Three modules:
  - `services/storage.py` — disk + url
  - `services/state_builder.py` — graph input prep
  - `services/persistence.py` — Supabase writes
  Or one `ImageProcessingService` class (preferred — see B-Q3).

#### B-D6. `BackgroundTasks` is in-process and unobservable
- **Severity:** Medium
- **Location:** `apps/backend/src/api/routes/po_parser.py:48`, `drive_webhook.py:115`
- **Issue:** Returns 202 to the client, then runs the LLM pipeline as a `BackgroundTask`. If the worker is killed between accept and finish, the work vanishes. No status endpoint, no retry.
- **Fix:** Persist the work item to Postgres before returning 202; a worker (`arq` / `Celery` / a dedicated coroutine reading the table) drains it. Same fix as B-D1 — both want a real queue.

---

### OPTIMIZATION

#### B-O1. Bulk upload runs files sequentially despite being `async`
- **Severity:** High
- **Location:** `apps/backend/src/api/routes/bulk.py:78-85`
  ```python
  for i, (filename_orig, contents) in enumerate(file_list):
      await _process_one_file(...)
  ```
- **Impact:** N files × per-file LLM round-trip latency. With 50 files × 4 s each = 200 s wall-clock. With a semaphore of 8 it's ~25 s.
- **Fix:**
  ```python
  sem = asyncio.Semaphore(int(os.getenv("BULK_CONCURRENCY", "8")))
  async def run(i, name, content):
      async with sem:
          await _process_one_file(request, graph, name, content, batch_id, i)
  await asyncio.gather(*(run(i, n, c) for i, (n, c) in enumerate(file_list)))
  ```
  Combine with B-D1 fix so the increment of `completed` is atomic.

#### B-O2. Whole-file `await file.read()` then `write_bytes`
- **Severity:** Medium
- **Location:** `apps/backend/src/api/routes/images.py:74-75`, `bulk.py:97-99`
- **Issue:** Buffers the whole upload in RAM, then writes synchronously to disk. For bulk uploads, a list of `(filename, bytes)` tuples is held in memory before any processing.
- **Fix:** Stream uploads chunk-by-chunk: `while chunk := await file.read(CHUNK_SIZE): out.write(chunk)`. For bulk: process each file as it arrives instead of pre-reading them all.

#### B-O3. Disk write is on the request thread, blocking the event loop
- **Severity:** Medium
- **Location:** `apps/backend/src/api/services/image_pipeline.py:26` (`filepath.write_bytes(contents)` inside an async-call path)
- **Fix:** Use `aiofiles` or `await asyncio.to_thread(filepath.write_bytes, contents)`.

#### B-O4. `StaticFiles` in production
- **Severity:** Low
- **Location:** `apps/backend/src/api/main.py:64`
- **Issue:** FastAPI's `StaticFiles` serves images from the same worker as API requests. Fine for dev, but in prod a 5 MB image hogs an event-loop worker for the duration of the download.
- **Fix:** Front with nginx / a CDN / S3+presigned URLs. Document the prod intent.

#### B-O5. `rewrite_tag_row` builds a fresh dict per row even when nothing needs rewriting
- **Severity:** Low
- **Location:** `apps/backend/src/api/services/url_rewriter.py:59-64`
- **Issue:** Always copies the row even when `image_url` is already canonical or absent.
- **Fix:** Short-circuit: if `rewrite_uploads_url(row.get("image_url")) == row.get("image_url")`, return `row` as-is.

#### B-O6. `/api/available-filters` is recomputed on every request
- **Severity:** Low
- **Location:** `apps/backend/src/api/routes/images.py:178-200`
- **Issue:** With no filters, the result is essentially the taxonomy intersected with what's in the DB — slow-changing and a perfect cache target.
- **Fix:** TTL cache (60 s) keyed on the filters dict. `cachetools.TTLCache` is one line.

#### B-O7. Health endpoint doesn't actually check anything
- **Severity:** Medium
- **Location:** `apps/backend/src/api/routes/health.py` (returns `{"status": "healthy"}` unconditionally)
- **Impact:** Orchestrators (k8s readiness probes, load balancers) can't tell that Supabase or the graphs are wedged.
- **Fix:** A `GET /health` for liveness (cheap, always 200 if the process is up) and `GET /ready` that verifies (a) `_image_graph_initialised`, (b) Supabase pool has a usable connection, (c) `WEBHOOK_SECRET` is configured. Return 503 on any failure.

---

### TESTING & OBSERVABILITY

#### B-T1. No tests
- **Severity:** High
- **Location:** No `tests/` directory under `apps/backend/`
- **Highest-leverage targets:**
  - Route contract tests using `httpx.AsyncClient` + `app.dependency_overrides` to stub the graph
  - `_parse_filter_params` and `rewrite_uploads_url` (pure functions)
  - `image_pipeline` (mock the supabase client)
  - The webhook secret middleware
- **Fix:** Add `pytest` + `pytest-asyncio` to dev deps; one `tests/conftest.py` that builds an `AsyncClient` against the FastAPI app with stubbed dependencies.

#### B-T2. No structured logging or request IDs
- **Severity:** Medium
- **Location:** Configured at `apps/backend/src/api/config.py:13-14` with stock `logging.basicConfig`.
- **Fix:** `structlog` (or `python-json-logger`) plus an `@app.middleware("http")` that sets a `X-Request-ID` (echo client header if present, else generate uuid4) and binds it to the logger context. All downstream logs carry it for free.

#### B-T3. No latency / RPS / error metrics
- **Severity:** Medium
- **Location:** No Prometheus exporter or OpenTelemetry hooks.
- **Fix:** `prometheus-fastapi-instrumentator` is one line of setup and gives you per-route latency histograms and counters. If you have OTel infra, prefer that.

#### B-T4. Env-var reads scattered across modules
- **Severity:** Medium
- **Location:** `config.py`, `middleware.py`, `routes/drive_webhook.py:39`, `services/url_rewriter.py:21, 31`
- **Issue:** No single place to see what the backend needs to boot. `WEBHOOK_SECRET` is read in two different files.
- **Fix:** A `pydantic_settings.BaseSettings` (`Settings` class) instantiated once at startup; everything else reads from it via `Depends(get_settings)`.

---

### MISC

- **B-L1** — `apps/backend/src/api/routes/bulk.py:8` imports `Depends` ✓ (it is used via `Annotated[..., Depends(...)]`); the subagent flag is a false positive — do not remove.
- **B-L2** — Public routes have no docstrings → empty descriptions in OpenAPI. Add a one-liner per route plus a `summary=`.
- **B-L3** — `apps/backend/src/api/routes/images.py:148, 175` return inconsistent pagination shapes (`items, limit, offset` vs `items, limit`). Standardise on a `Page[T]` model.
- **B-L4** — `Dockerfile`: pin base image by digest, add `HEALTHCHECK`, run as non-root user, copy `pyproject.toml` first then source so the dep layer caches.

---

## A note on one finding I dropped

The image-tagging review subagent flagged that **the 8 taggers run sequentially because of the `for name in TAGGER_NODE_NAMES` loop in `graph_builder.py`**. That is **incorrect**. Inspecting `apps/agents/src/agents/image_tagging/graph_builder.py:36-43`:

```python
for name in TAGGER_NODE_NAMES:
    builder.add_edge("vision_analyzer", name)   # fan-out
    builder.add_edge(name, "tag_validator")     # fan-in
```

This is the standard LangGraph fan-out: edges from one node to many siblings cause LangGraph to schedule the siblings concurrently. The "fix" the subagent proposed is byte-identical to the code already on disk. Real bottleneck for parallelism is **A-O1 (per-call `ChatOpenAI` construction)**, not the graph wiring.

---

## Suggested order of attack

**Quick wins (a few hours each, big payoff):**
1. **A-O1** — `lru_cache` the `ChatOpenAI` factory (5 lines).
2. **A-Q1** — `_clients.py` module to consolidate the singleton pattern (~30 lines, deletes ~40).
3. **A-Q2** — `TAGGER_SPECS` table + factory; delete the 8 wrappers (~20 lines, deletes ~65).
4. **B-O1** — `asyncio.gather` + `Semaphore` in `_run_bulk_batch` (~10 lines).
5. **A-O2** — `lru_cache` `taxonomy.get_flat_values` (1 decorator).
6. **B-O7 / B-D4** — Real health check + eager graph build in `lifespan` (~30 lines).

**Sprint-sized:**
7. **B-Q2** — Pydantic response models on every route. Mostly mechanical, big OpenAPI win.
8. **A-D2** — Move "Raw Extract JSON" duplicate-detection out of validator into Airtable client.
9. **B-D1 / B-D6** — Persist `BATCH_STORAGE` + replace `BackgroundTasks` with a real queue. Probably one Postgres table + a polling worker is enough.
10. **A-Q3** — Split `extract_po.py` into `normalize / parsing / node`. Unlocks A-T1 tests on the deterministic helpers.

**Ongoing:**
11. **A-T1 / B-T1** — Stand up a test suite. Start with the four pure-function modules per app; aim for graph-level fixture tests once the easy stuff is covered.
12. **B-T2 / B-T3** — Structured logging + request IDs + Prometheus metrics.
13. **A-D3 / B-T4** — Consolidate env vars behind one `BaseSettings` per app.

Tackle 1–6 first; they are net code reductions and unlock measurable performance and developer-ergonomics wins without architectural risk.
