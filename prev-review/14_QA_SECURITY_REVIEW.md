# QA & Security Review — `apps/agents` and `apps/backend`

**Date:** 2026-04-20
**Reviewer:** QA / Security
**Scope:** `apps/agents/` (LangGraph agents + shared service clients) and `apps/backend/` (FastAPI HTTP layer).
**Out of scope:** `apps/frontend/`, `gas/`, `docs/`, infra/CI configuration, third-party dependencies' internals.

---

## Executive summary

The codebase is functional and the recent commits show the team is actively hardening it (CORS whitelist, lifespan shutdown, narrower exception handling, singleton pooling). However, several **critical** issues remain that should block production exposure to untrusted traffic:

1. **All HTTP endpoints are unauthenticated** except the two webhooks. Any caller can run expensive LLM pipelines, list/search images, and burn OpenAI quota.
2. **No file-size or request-body limits** on uploads (`/analyze-image`, `/bulk-upload`, `/webhook/drive-image`). Trivial disk/memory DoS.
3. **`limit` / `offset` query params are unbounded** on listing endpoints. Trivial DB DoS.
4. **Global exception handler leaks `str(exc)` and `type(exc).__name__`** to clients — information disclosure.
5. **`X-Forwarded-Proto` / `X-Forwarded-Host` are trusted unconditionally** and persisted into URLs stored in Supabase — open-redirect / cache-poisoning vector.
6. **`BATCH_STORAGE` is an in-process dict that is never evicted** — slow memory leak; also lost on restart.
7. **`time.sleep(2)` inside an async function** (`gas_callback/client.py`) blocks the event loop.
8. **`threading.Lock` is used inside async checkpointer init/teardown** — wrong primitive; can deadlock under concurrency.

Issue counts (after de-duping subagent findings and verifying against source):

| Severity | Count |
|----------|-------|
| Critical | 6 |
| High     | 11 |
| Medium   | 12 |
| Low / Info | 10 |
| **Total** | **39** |

The rest of this document lists every finding with file paths, line numbers, impact, and a concrete fix.

---

## Findings — `apps/backend/`

### CRITICAL

#### B-C1. All read/write API endpoints are unauthenticated
- **Category:** Security — AuthN/AuthZ
- **Location:**
  - `apps/backend/src/api/routes/images.py:54` (`/api/taxonomy`)
  - `apps/backend/src/api/routes/images.py:59` (`/api/analyze-image`)
  - `apps/backend/src/api/routes/images.py:130` (`/api/tag-image/{image_id}`)
  - `apps/backend/src/api/routes/images.py:141` (`/api/tag-images`)
  - `apps/backend/src/api/routes/images.py:151` (`/api/search-images`)
  - `apps/backend/src/api/routes/images.py:178` (`/api/available-filters`)
  - `apps/backend/src/api/routes/bulk.py:88` (`/api/bulk-upload`)
  - `apps/backend/src/api/routes/bulk.py:112` (`/api/bulk-status/{batch_id}`)
- **Issue:** No `Depends(...)` auth check is wired into any of these. Only `/po-parser` and `/webhook/drive-image` validate a webhook secret.
- **Impact:** Any unauthenticated caller can (a) trigger expensive OpenAI vision + tagging pipelines and run up cost, (b) list and search the full image database, (c) upload arbitrary files, (d) enumerate `batch_id` UUIDs for status data.
- **Fix:** Add a single `verify_api_key` dependency (Header `X-API-Key`, value compared via `hmac.compare_digest`). Apply it at the router level: `router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])`. Alternatively front the API with an authenticating reverse proxy and document that explicitly.

#### B-C2. No file-size limits on uploads
- **Category:** Security — DoS / storage exhaustion
- **Location:**
  - `apps/backend/src/api/routes/images.py:74` (`await file.read()` — entire body into RAM, then `filepath.write_bytes(contents)`)
  - `apps/backend/src/api/routes/bulk.py:97-99` (loops `await f.read()` over an unbounded list of `UploadFile`)
  - `apps/backend/src/api/routes/drive_webhook.py:36,50` (`await request.json()` then `base64.b64decode(image_b64)` — no size cap)
- **Issue:** No per-file or aggregate body-size validation. The whole payload is buffered in memory and then written to disk under `apps/backend/uploads/`.
- **Impact:** Single 10GB request OOMs the worker; sustained uploads fill the disk. For `/bulk-upload`, a request with 10k files compounds the issue.
- **Fix:**
  - Read with a guard: `contents = await file.read(MAX_BYTES + 1); if len(contents) > MAX_BYTES: raise HTTPException(413, ...)`.
  - Set `MAX_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 25 * 1024 * 1024))` in `api/config.py`.
  - For `/bulk-upload`, also cap `len(files)` (e.g. 50) and total bytes.
  - Configure your ASGI server with `--limit-max-body-size` (uvicorn) or equivalent so payloads are rejected before they touch the app.

#### B-C3. Unbounded `limit` / `offset` on listing endpoints
- **Category:** Security — DoS
- **Location:**
  - `apps/backend/src/api/routes/images.py:144` (`limit: int = 20, offset: int = 0`)
  - `apps/backend/src/api/routes/images.py:162` (`limit: int = 50`)
- **Issue:** No `Query(..., ge=..., le=...)` bounds. `?limit=999999999&offset=999999999` is accepted and forwarded to Supabase.
- **Impact:** Trivial DoS against the database, plus huge response serialization in the API layer.
- **Fix:**
  ```python
  from fastapi import Query
  limit: int = Query(20, ge=1, le=100),
  offset: int = Query(0, ge=0, le=10_000),
  ```

#### B-C4. Global exception handler leaks internal error details
- **Category:** Security — Information disclosure
- **Location:** `apps/backend/src/api/main.py:41-47`
- **Issue:** The handler returns `{"detail": str(exc), "type": type(exc).__name__}`. Many third-party libraries (psycopg, openai, pyairtable) embed connection strings, prompts, or stack-trace fragments in exception messages.
- **Impact:** Attackers can probe endpoints to map internal libraries, hostnames, table names, and prompt structure.
- **Fix:** Log the full exception server-side (already done via `logger.exception`), return a generic body to the client:
  ```python
  return JSONResponse(status_code=500, content={"detail": "Internal server error"})
  ```
  If correlation is needed, include a `request_id` (uuid4) and log it alongside.

#### B-C5. `X-Forwarded-*` headers are trusted unconditionally and persisted
- **Category:** Security — Open redirect / cache poisoning / stored URL injection
- **Location:** `apps/backend/src/api/services/url_rewriter.py:24-30`, used by `apps/backend/src/api/services/image_pipeline.py` to generate `image_url` that is **stored in Supabase**.
- **Issue:** Any client can send `X-Forwarded-Host: evil.example` and `X-Forwarded-Proto: https`, and the resulting URL is written into the database row for the image. There is no scheme whitelist or trusted-proxy check.
- **Impact:** An attacker can poison stored URLs so the frontend or downstream consumers fetch images from an attacker-controlled host. Also possible: `X-Forwarded-Proto: javascript` if proto isn't constrained, leading to XSS when the URL is rendered.
- **Fix:**
  - Prefer `API_PUBLIC_BASE_URL` and document it as **required** in production.
  - Only honour `X-Forwarded-*` when the immediate peer is a known trusted proxy (or via Starlette's `ProxyHeadersMiddleware` with `trusted_hosts`).
  - Reject `proto` values not in `{"http", "https"}` and `host` values containing `/`, `\`, whitespace, or control chars.

#### B-C6. `BATCH_STORAGE` is an unbounded in-process dict
- **Category:** Security/Best practice — Memory leak + state loss
- **Location:** `apps/backend/src/api/config.py:22`, populated/never-evicted in `apps/backend/src/api/routes/bulk.py:102-122`.
- **Issue:** Every batch upload adds an entry; nothing ever deletes it. Also: state is per-worker, so under `--workers > 1` a status request hitting the wrong worker returns 404.
- **Impact:** Slow OOM on long-running pods; non-deterministic 404s in multi-worker deploys.
- **Fix:** Move to Redis (or the existing Postgres) with a TTL; add a cleanup job that drops `completed`/`failed` batches older than e.g. 24 h. At minimum, add an `created_at` and a periodic in-process cleanup.

---

### HIGH

#### B-H1. CORS: wildcard methods + wildcard headers + `allow_credentials=True`
- **Category:** Security
- **Location:** `apps/backend/src/api/main.py:50-62`
- **Issue:** `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=True`, and the default origin list silently falls back to `http://localhost:3000` if `CORS_ALLOW_ORIGINS` is unset in prod.
- **Impact:** If ever combined with cookie/session auth, this expands the CSRF surface. The silent fallback risks shipping a dev origin to prod.
- **Fix:** Restrict methods to `["GET", "POST"]`, headers to the ones actually used (`["Content-Type", "X-API-Key", "x-webhook-secret"]`), and **fail fast** if `CORS_ALLOW_ORIGINS` is unset in non-dev environments.

#### B-H2. `_process_one_file` runs sequentially in `_run_bulk_batch`
- **Category:** Best practice — Performance / async misuse
- **Location:** `apps/backend/src/api/routes/bulk.py:78-85` (`for ... await ...`)
- **Issue:** The bulk endpoint awaits each file one at a time inside the request handler. The handler returns `"status": "processing"` but does not actually background the work — the client waits the full duration and there is no parallelism between files.
- **Impact:** Misleading API contract (response shape implies async), and the wall-clock latency for N files is N × (LLM round-trip).
- **Fix:** Either (a) launch with `BackgroundTasks` like `drive_webhook.py` does, or (b) fan out with `asyncio.gather(*[_process_one_file(...) for ...])` with a `Semaphore(N)` to cap concurrency.

#### B-H3. Drive webhook secret comparison is not constant-time
- **Category:** Security — Timing side-channel
- **Location:** `apps/backend/src/api/routes/drive_webhook.py:38-41`
- **Issue:** `if not secret or secret != expected:` uses Python `==`, which short-circuits per-character.
- **Impact:** Network-side timing attack against the webhook secret. Mitigated in practice by network jitter, but trivial to fix.
- **Fix:** Use the existing `verify_webhook_secret` dependency from `api/middleware.py:9-18`, or `hmac.compare_digest(secret.encode(), expected.encode())`.

#### B-H4. Drive webhook accepts secret in JSON body
- **Category:** Security
- **Location:** `apps/backend/src/api/routes/drive_webhook.py:38`
- **Issue:** `secret = body.get("secret") or request.headers.get(...)`. Secrets in request bodies are more likely to end up in access logs, error reports, and proxy traces than headers.
- **Impact:** Higher chance of secret leaking through logging infrastructure.
- **Fix:** Require the `x-webhook-secret` header only. The README/GAS doc should be updated to send the header.

#### B-H5. `base64.b64decode` raises uncaught `binascii.Error`
- **Category:** Best practice / Security (paired with B-C4)
- **Location:** `apps/backend/src/api/routes/drive_webhook.py:50`
- **Issue:** Invalid base64 throws `binascii.Error`, which falls into the global handler and returns `str(exc)` to the caller.
- **Impact:** 500 instead of 400; combined with B-C4, leaks library internals.
- **Fix:** `try: contents = base64.b64decode(image_b64, validate=True) except (binascii.Error, ValueError): raise HTTPException(400, "Invalid base64")`.

#### B-H6. No rate limiting anywhere
- **Category:** Security — Cost/resource abuse
- **Location:** All routers
- **Issue:** Without auth (B-C1), a single client can drive the OpenAI bill arbitrarily high.
- **Fix:** Add `slowapi` (or run behind a rate-limiting reverse proxy) with stricter limits on `/api/analyze-image` and `/api/bulk-upload` (e.g. `5/min` per IP and per API key).

#### B-H7. `time.sleep(2)` inside async path used by webhook
- **Category:** Best practice — Async correctness
- **Location:** `apps/agents/src/services/gas_callback/client.py:50`, called from `apps/backend/src/api/routes/drive_webhook.py:79,101` (inside `async def _process`).
- **Issue:** `time.sleep` blocks the entire event loop. When the GAS callback fails and we retry, every other request and background task on the worker stalls for 2 seconds.
- **Fix:** `await asyncio.sleep(2)`.

#### B-H8. `threading.Lock` used inside async checkpointer init / teardown
- **Category:** Best practice — Async correctness
- **Location:** `apps/agents/src/services/checkpointer.py:32, 108, 163` (`_async_state_lock = threading.Lock()` then `with _async_state_lock:` inside `async def get_async_checkpointer` / `close_async_checkpointer`).
- **Issue:** A `threading.Lock` held across `await` points can starve the event loop and, under concurrent first-access, deadlock if anything inside the locked region also waits on the loop. The first call to `get_async_checkpointer` performs `await AsyncConnection.connect(...)` and `await saver.setup()` while holding a sync lock.
- **Impact:** Under concurrent cold-start traffic the worker can stall; in worst case it deadlocks until the sync lock is reclaimed.
- **Fix:** Use `asyncio.Lock()` for the async variant. Also: don't hold the lock across the `await` for `connect` / `setup`; do double-checked locking with a short critical section.

#### B-H9. Bulk upload has no per-file size cap and reads all files into RAM up front
- **Category:** Security — DoS
- **Location:** `apps/backend/src/api/routes/bulk.py:97-99`
- **Issue:** Reads every uploaded file into a `list[tuple[str, bytes]]` before processing. With N files × 25 MB, RSS spikes by N × 25 MB.
- **Fix:** Stream from `UploadFile` per iteration, save to disk, then process by path. Alternatively cap `MAX_BULK_FILES = 25`.

#### B-H10. Background task writes to in-process state without locking
- **Category:** Best practice — Concurrency
- **Location:** `apps/backend/src/api/routes/bulk.py:38-75` (writes `BATCH_STORAGE[batch_id]["results"][index]` and `["completed"]` from concurrent tasks)
- **Issue:** When bulk processing is parallelised (which fix B-H2 implies), `BATCH_STORAGE[batch_id]["completed"] += 1` and the status flip on line 74-75 are not atomic.
- **Fix:** Wrap the increment and status flip in an `asyncio.Lock` keyed by `batch_id`, or move state to Redis with atomic ops.

#### B-H11. Drive webhook silently coerces unknown extensions to `.jpg`
- **Category:** Best practice — Input validation
- **Location:** `apps/backend/src/api/routes/drive_webhook.py:51-53`
- **Issue:** If `filename_orig` has an unknown suffix the code silently rewrites it to `.jpg`, then writes arbitrary bytes to a file claiming to be a JPEG.
- **Impact:** Wrong content-type when re-served from `/uploads/...`; downstream tooling may misclassify.
- **Fix:** Reject unknown types with 400 instead of coercing.

---

### MEDIUM

#### B-M1. Endpoints return untyped `dict`s — no `response_model`
- **Location:** `images.py:54, 59, 130, 141, 151, 178`, `bulk.py:88, 112`
- **Impact:** OpenAPI schema is incomplete, accidental fields can leak into responses, no runtime response validation.
- **Fix:** Define `pydantic.BaseModel` response classes and pass `response_model=...` per route.

#### B-M2. `/api/analyze-image` re-wraps errors as `f"Analysis failed: {e}"`
- **Location:** `apps/backend/src/api/routes/images.py:83-84`
- **Impact:** Echoes raw exception text back to the client (similar to B-C4 but local).
- **Fix:** Log full exception, return a generic 500.

#### B-M3. No `Content-Length` enforcement on JSON bodies
- **Location:** `drive_webhook.py:36`, `po_parser.py` (request bodies)
- **Fix:** Configure ASGI server body limit and/or use `Request.body()` with size check before `json()`.

#### B-M4. `/uploads` is mounted as static and not authenticated
- **Location:** `apps/backend/src/api/main.py:64`
- **Issue:** Anyone who knows or guesses the UUID can fetch the original image. UUIDs are not enumerable, so this is acceptable for low-sensitivity images, but if the images contain customer/PII content it should be gated.
- **Fix:** Either keep public (document it explicitly) or add a per-image signed-URL handler.

#### B-M5. Logging of image URLs and filenames is unsanitized
- **Location:** Throughout `routes/` and `services/image_pipeline.py`
- **Issue:** User-supplied filenames are written verbatim into logs (`logger.exception("Bulk process failed for file %s: %s", index, e)` — this one's safe, but elsewhere `filename_orig` is logged).
- **Impact:** Log injection (CR/LF) and potential PII leakage.
- **Fix:** Sanitize: `re.sub(r"[\r\n\t]", " ", filename)` before logging; redact obviously sensitive fields.

#### B-M6. No security headers
- **Location:** `apps/backend/src/api/main.py`
- **Missing:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, `Content-Security-Policy` (for `/uploads`), `Cache-Control: no-store` on JSON responses.
- **Fix:** Add a small middleware that injects these headers.

#### B-M7. Dockerfile likely runs as root and lacks healthcheck
- **Location:** `apps/backend/Dockerfile`
- **Fix:** `USER appuser` (create a non-root user); add `HEALTHCHECK CMD curl -fsS http://localhost:8000/health || exit 1`. Also pin `python:3.x-slim` to a digest.

#### B-M8. `WEBHOOK_SECRET` and `API_PUBLIC_BASE_URL` are read at request time, not validated at startup
- **Location:** `middleware.py:12`, `drive_webhook.py:39`, `url_rewriter.py:21`
- **Issue:** A misconfigured deploy (missing `WEBHOOK_SECRET`) returns 401 with the generic "Missing webhook secret" message instead of failing to boot.
- **Fix:** Validate required env vars in `lifespan` startup; refuse to start if missing in production.

#### B-M9. PO parser webhook: missing/weak idempotency
- **Location:** `apps/backend/src/api/routes/po_parser.py` (and the corresponding agent)
- **Issue:** GAS may retry on network errors. There is no `Idempotency-Key` handling in the route, and dedup relies entirely on the Airtable PO-number lookup downstream.
- **Fix:** Accept a GAS message-id, persist `(message_id, status)`, return cached response on retry.

#### B-M10. `Optional` return types are used inconsistently
- **Location:** Throughout — mix of `X | None` and `Optional[X]`
- **Fix:** Pick one (the rest of the file uses `X | None`); enable `ruff` `UP007`.

#### B-M11. No tests in `apps/backend/`
- **Impact:** Regressions in routing, auth, error mapping go undetected.
- **Fix:** Add a `tests/` package with `httpx.AsyncClient` smoke tests against the main router; mock the graph dependency via `app.dependency_overrides`.

#### B-M12. `BackgroundTasks` does not survive process restart
- **Location:** `apps/backend/src/api/routes/drive_webhook.py:115`
- **Issue:** If the worker is restarted between accepting the request and finishing the LLM call, the image is silently dropped (no GAS callback, no Supabase row).
- **Fix:** Persist the work item to Postgres before returning 202; have a worker (or `arq`/`Celery`) drain the queue.

---

### LOW / INFO

- **B-L1** — `/health` returns `dict` without a model. Add a `HealthResponse` Pydantic model for OpenAPI clarity. (`apps/backend/src/api/routes/health.py:13`)
- **B-L2** — `apps/backend/uploads/` is committed; ensure it's `.gitignored` and not packaged into the Docker image.
- **B-L3** — Public routes lack docstrings → empty OpenAPI descriptions.
- **B-L4** — `apps/backend/pyproject.toml` deps appear unpinned (`>=` only). Pin with `~=` or full versions for reproducible builds.
- **B-L5** — No structured (JSON) logging configured; only `logging.basicConfig`. Production aggregation needs JSON.
- **B-L6** — `image_pipeline.save_image` does not sanitize the original filename. Currently safe because it derives the saved name from a UUID, but the helper signature should make that contract explicit.

---

## Findings — `apps/agents/`

### CRITICAL

#### A-C1. SSRF surface in the GAS callback URL
- **Category:** Security — SSRF
- **Location:** `apps/agents/src/services/gas_callback/client.py:21-38`
- **Issue:** `webapp_url` comes from env (`GAS_WEBAPP_URL`) and is used as-is in `client.post(...)` with `follow_redirects=True`. If the env var is ever sourced from a less-trusted location (e.g. a per-tenant config), or if a misconfigured deploy points it at an internal address, the worker will happily POST to internal endpoints.
- **Impact:** Internal-network reach from the worker (e.g. cloud metadata at `169.254.169.254`) and unbounded redirect chain.
- **Fix:** Validate the URL at startup: scheme must be `https`, host must not resolve to RFC1918/loopback/link-local. Set `follow_redirects=False` (GAS Web Apps redirect to `script.googleusercontent.com`, which `httpx` handles, but you can whitelist that hostname instead of allowing arbitrary redirects).

#### A-C2. No timeout on synchronous OpenAI calls
- **Category:** Best practice — Resource exhaustion
- **Location:** `apps/agents/src/services/openai/client.py` (sync `chat.completions.create` calls used by PO-parser nodes)
- **Issue:** No explicit `timeout=` is passed; the default in the OpenAI SDK is generous (10 minutes).
- **Impact:** A stuck call holds a thread and can prevent graceful shutdown.
- **Fix:** Pass `timeout=30` (or read from settings). Same applies to the async `ainvoke` paths in image tagging.

#### A-C3. Airtable formula escaping is incomplete
- **Category:** Security — Formula injection
- **Location:** `apps/agents/src/services/airtable/client.py:14-15, 109-110`
- **Issue:** `_escape_formula_value` only escapes `\` and `'`. PO numbers come from LLM-extracted text (effectively user-controlled via the email body). Crafted input like `') OR FIND('x','y` could change the formula's logic.
- **Impact:** Duplicate-detection bypass; potential exfiltration of unrelated records via crafted formulas.
- **Fix:** Whitelist characters: `if not re.fullmatch(r"[A-Za-z0-9._\-/]+", po_number): return None` before constructing the formula. PO numbers are short and structured — a strict allowlist is appropriate.

#### A-C4. `time.sleep(2)` inside an async function (also tracked as B-H7)
- **Location:** `apps/agents/src/services/gas_callback/client.py:50`
- **Fix:** `await asyncio.sleep(2)`.

#### A-C5. `threading.Lock` used inside async checkpointer (also tracked as B-H8)
- **Location:** `apps/agents/src/services/checkpointer.py:32, 108, 163`
- **Fix:** Switch the async variant to `asyncio.Lock`; shrink the critical section so `await connect/setup` is not held under the lock.

#### A-C6. `base64.b64decode(..., validate=False)` for arbitrary attachments without magic-byte check
- **Category:** Security — Input validation
- **Location:** `apps/agents/src/agents/po_parser/tools/file_helpers.py:15, 20`
- **Issue:** Attachments from email are decoded with validation off and written to temp files, with no signature check. If a downstream tool ever parses these by extension, polyglot files can mislead it.
- **Impact:** Currently low (only consumed by deterministic Python parsers), but the contract is brittle.
- **Fix:** After decoding, check magic bytes against the expected MIME (PDF `%PDF-`, ZIP `PK\x03\x04` for XLSX, etc.) and reject mismatches.

---

### HIGH

#### A-H1. Image preprocessor has no size or pixel-bomb guard
- **Location:** `apps/agents/src/agents/image_tagging/nodes/preprocessor.py:25, 30`
- **Issue:** `Image.open(BytesIO(base64.b64decode(...)))` will happily decompress a small payload into multi-GB pixel data (decompression bomb).
- **Fix:** Set `PIL.Image.MAX_IMAGE_PIXELS` to a sane cap; verify `len(raw) <= MAX_IMAGE_BYTES` before decode; call `img.verify()` or check `img.size` before further processing.

#### A-H2. Bare-ish `except (Exception,):` in checkpointer close paths
- **Location:** `apps/agents/src/services/checkpointer.py:95, 168`
- **Issue:** `except (Exception,):` is functionally `except Exception:` — not technically "bare" — but is unusual stylistically and swallows every error during shutdown without distinction. The accompanying `logger.exception(...)` does preserve the trace, so impact is moderate, not critical.
- **Fix:** Use `except Exception:` or, better, narrow to `(PsycopgError, ConnectionError, OSError)` matching the init paths.

#### A-H3. No `max_tokens` on LLM calls
- **Location:** `apps/agents/src/services/openai/client.py`, `apps/agents/src/agents/image_tagging/nodes/vision.py`, `taggers.py`
- **Issue:** Without a token cap, a degenerate prompt or input can produce a very long completion, increasing latency and cost.
- **Fix:** Always pass `max_tokens` (e.g. 1024 for tagging, 2048 for vision description).

#### A-H4. Retry loop uses naive backoff and ignores `Retry-After`
- **Location:** `apps/agents/src/agents/image_tagging/nodes/vision.py:60-67`, `taggers.py:56-63`
- **Issue:** Hand-rolled `await asyncio.sleep(1 * (2**attempt))` with no jitter and no respect for the OpenAI `Retry-After` header.
- **Fix:** Use `tenacity` with `wait_random_exponential(multiplier=1, max=20)` and `stop_after_attempt(3)`; on 429, parse `Retry-After`.

#### A-H5. Errors are concatenated into `state["errors"]` and forwarded to GAS verbatim
- **Location:** `apps/agents/src/agents/po_parser/nodes/{classifier,extract_po,airtable_writer,gas_callback}.py`
- **Issue:** Raw `str(e)` from third-party clients is appended to state and later included in the GAS callback payload.
- **Impact:** Internal info (URLs, table IDs, prompt fragments) leaves the worker.
- **Fix:** Map exceptions to short, sanitized labels (`"airtable_write_failed"`, `"llm_parse_failed"`); log the full trace server-side only.

#### A-H6. Per-node singletons initialized without a lock
- **Location:** `apps/agents/src/agents/po_parser/nodes/classifier.py:18-24`, `extract_po.py:26-55`, `validator.py:16-22`, `airtable_writer.py:16-23`, `gas_callback.py:15-22`
- **Issue:** Module-level `_openai`/`_airtable_client` are lazy-initialized without `threading.Lock` or `functools.lru_cache`. Concurrent first-access can construct multiple clients (which then leak HTTP pools).
- **Fix:** Wrap each in `functools.lru_cache(maxsize=1)` or use a `threading.Lock`.

#### A-H7. Email body / PII goes into logs and state
- **Location:** Multiple `po_parser/nodes/*.py`
- **Issue:** Sender, subject, attachment filenames, and parts of the body land in INFO-level logs and into `state` (which is checkpointed to Postgres).
- **Impact:** PII at rest in logs and checkpointer DB; harder GDPR posture.
- **Fix:** Hash or truncate sender; don't log body. If checkpointer persistence is intended for replay, document the data-retention policy.

#### A-H8. JSON parsing of LLM output has no size limit
- **Location:** `apps/agents/src/agents/po_parser/nodes/validator.py:68`, `extract_po.py:337, 349`
- **Issue:** Adversarial LLM output (or a corrupted retry) could yield huge / deeply nested JSON. Python's `json.loads` is generally safe, but parsing a 100MB string still costs CPU and memory.
- **Fix:** Cap raw response length before `json.loads` (e.g. `raw[:200_000]`).

#### A-H9. Attachment uploads to Airtable have no size cap
- **Location:** `apps/agents/src/agents/po_parser/nodes/airtable_writer.py:89-105`
- **Issue:** Whatever GAS sends is uploaded. A malicious / accidental large attachment can blow Airtable storage quota.
- **Fix:** `if len(raw) > MAX_ATTACHMENT_BYTES: skip + record warning`.

#### A-H10. `langgraph.json` and `pyproject.toml` deps are unpinned
- **Location:** `apps/agents/pyproject.toml`
- **Issue:** Minimum-version specifiers (`langgraph>=0.2`, `openai>=1.0`) allow major-version upgrades on rebuild.
- **Fix:** Use a lockfile (`uv lock` is already in use — verify it's committed and read in CI) and prefer `~=` constraints in `pyproject`.

#### A-H11. No idempotency in Airtable writer / GAS callback
- **Location:** `apps/agents/src/agents/po_parser/nodes/airtable_writer.py`, `gas_callback.py`
- **Issue:** A graph re-run for the same email creates a duplicate Airtable record (the lookup by PO-number helps but isn't atomic with the create).
- **Fix:** Use the email message-id as an idempotency key, persisted alongside the Airtable record id.

---

### MEDIUM

- **A-M1** — Confidence thresholds hardcoded (`image_tagging/configuration.py:5,12-15`, `po_parser/nodes/routing.py:8`). Move to env / settings.
- **A-M2** — Pydantic models lack `max_length` on string fields (`po_parser/schemas/po.py`, `email.py`, `image_tagging/schemas/models.py`).
- **A-M3** — Token usage is logged but not aggregated into state; no per-invocation cost visibility.
- **A-M4** — No request-correlation ID propagated through async LLM calls; debugging across nodes requires manual correlation.
- **A-M5** — No circuit breaker / fast-fail when OpenAI/Airtable/Supabase are down; every request waits for the per-call timeout.
- **A-M6** — `extract_po.py` helpers (`_strip_html`, `_clean_body`, `_parse_date`, etc.) have partial type hints.
- **A-M7** — Missing docstrings on public-ish helpers in `services/airtable/client.py` and `services/gas_callback/client.py`.
- **A-M8** — `services/supabase/client.py` `list_tag_images`/`search_images_filtered` use offset pagination; consider cursor-based for large sets.
- **A-M9** — `OPENAI_API_KEY` is required at module import for image_tagging settings (`image_tagging/settings.py:11-13`). Failing at import bubbles unhelpful tracebacks; defer the check to first use.
- **A-M10** — `pyairtable` errors caught broadly via `except Exception:`. Narrow to `pyairtable.api.types`-specific errors plus `RequestException`.
- **A-M11** — No tests under `apps/agents/`. The graph wiring is well-suited to deterministic snapshot tests with mocked services.
- **A-M12** — `langgraph.json` should be reviewed: confirm only the intended graphs are exposed and that no debug/dev graphs leak into prod images.

---

### LOW / INFO

- **A-L1** — `Dockerfile` for agents: confirm non-root user and pinned base image digest.
- **A-L2** — Several `# type: ignore` comments in `services/checkpointer.py` could be removed by typing the `_state`/`_async_state` dicts more precisely.
- **A-L3** — `services/openai/client.py` should record `total_tokens` into state for cost telemetry.
- **A-L4** — Redundant `from __future__ import annotations` is fine on Python 3.11 but unnecessary; the recent commit `ee63597` already removes some.

---

## Suggested remediation order

1. **Today (block prod traffic until done):**
   - B-C1 (auth) — gate `/api/*` behind a single API-key dependency.
   - B-C2 (file size limits).
   - B-C3 (`limit`/`offset` bounds).
   - B-C4 (generic 500 body).
   - B-C5 (`X-Forwarded-*` validation or hard-require `API_PUBLIC_BASE_URL`).
   - B-H7 / A-C4 (replace `time.sleep` in async).
   - B-H8 / A-C5 (`asyncio.Lock` in async checkpointer).

2. **This week:**
   - B-C6 (move `BATCH_STORAGE` out of process or evict).
   - B-H1 / B-H3 / B-H4 / B-H5 (CORS tightening, webhook constant-time + header-only).
   - B-H6 (rate limiting).
   - A-C1 (SSRF guard on `GAS_WEBAPP_URL`).
   - A-C2 / A-H3 (timeouts + `max_tokens` on every LLM call).
   - A-C3 (Airtable formula whitelist).
   - A-H1 (image bomb guard).

3. **This sprint:**
   - All MEDIUM items, especially response models (B-M1), idempotency (A-H11 / B-M9), structured logging (B-L5), and a baseline test suite (A-M11 / B-M11).

---

## Notes on subagent findings

A few items from automated review needed correction during verification:

- The `except (Exception,):` in `services/checkpointer.py` was flagged "Critical" by the agent reviewer; in fact it is functionally identical to `except Exception:` and is paired with `logger.exception` (which preserves the trace). Downgraded to **High** as a style/clarity issue, not a swallowed-exception bug.
- The "missing timeout" finding on `gas_callback/client.py` was misread: a timeout *is* configured via `httpx.Timeout(float(self.settings.timeout))`. The real bug in that file is the **blocking `time.sleep` in an async function** (B-H7 / A-C4) and `follow_redirects=True` without a host whitelist (A-C1).
- The async-checkpointer concurrency bug (B-H8 / A-C5) was missed by both subagents and is the most likely production-incident cause in this list.
