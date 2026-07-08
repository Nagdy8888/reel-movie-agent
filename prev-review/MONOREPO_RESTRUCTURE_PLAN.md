# Monorepo Restructure — Execution Plan

**Companion to:** `REVIEW.md` (specifically §6 "Architecture / Design Pattern Recommendations" and §9 "Repository Separation Recommendations")
**Status:** Completed. Executed on 2026-04-10.
**Owner:** _assign on pickup_
**Date drafted:** 2026-04-09

---

## 0. TL;DR

Restructure `apps/agents/` into two workspace members and adopt `uv` as the workspace tool, so the LangGraph agent layer and the FastAPI HTTP layer can be deployed independently in the future without changing the directory layout again.

```
Before                                  After
──────                                  ─────
apps/agents/                            apps/agents/        ← LangGraph deployable (one langgraph.json)
├── src/                                ├── src/agents/{po_parser,image_tagging}/
│   ├── api/                            ├── src/services/{airtable,openai,supabase,gas_callback}/
│   ├── po_parser/                      ├── pyproject.toml
│   ├── image_tagging/                  ├── langgraph.json     ← single top-level
│   └── services/                       └── Dockerfile         ← placeholder for future LG-server build
├── tests/
├── Dockerfile                          apps/backend/       ← FastAPI (was `apps/agents` `src/api/`)
├── requirements.txt                    ├── src/api/{main.py, middleware.py}
└── langgraph.json                      ├── pyproject.toml
                                        ├── Dockerfile
apps/frontend/                          └── uploads/
docker-compose.yml                      apps/frontend/      ← unchanged
                                        pyproject.toml      ← uv workspace root
                                        uv.lock             ← committed
                                        docker-compose.yml  ← rewritten
```

**Key properties:**
- One LangGraph deployable (`apps/agents/`) hosts both `po_parser` and `image_tagging` graphs under a single top-level `langgraph.json`. This follows the LangGraph server default project schema and lets us run `langgraph build` / `langgraph deploy` against it later.
- The FastAPI HTTP layer moves out into `apps/backend/`. Today it depends on the `agents` workspace package and imports the graph + service objects directly. Later it can be flipped to call the LangGraph server over HTTP without any directory changes.
- `uv` becomes the workspace tool. One root `pyproject.toml`, one committed `uv.lock`, two workspace members (`apps/agents`, `apps/backend`).
- No business-logic changes. No new features. This is purely structural.

---

## 1. Why this change

Pulled directly from `REVIEW.md`:

- **Q2 (High):** `apps/agents` `src/api/main.py` is a ~580-LOC god file mixing HTTP routing, image processing, DB persistence, and graph orchestration.
- **Q3 (High):** Service clients are imported inside endpoint handlers (`main.py:128, 198, 216, 268, 333, 397, 407, 514, 524, 541, 561`), defeating dependency injection and making the code untestable.
- **§9 (Medium / structural):** The unified `apps/agents/` couples the LangGraph runtime to the FastAPI gateway, blocking a future independent deploy of the LangGraph server.
- **M3 (Medium):** Container runs as root because the single Dockerfile never drops privileges. We get to fix this for free as part of the rewrite.

This plan addresses the **structural** part of those findings (Q2/Q3 surface-level relocation, §9 boundary, M3 non-root). It does **not** refactor the internals of `main.py` further, and it does **not** introduce DI, checkpointers, HITL, auth, or upload limits. Those are tracked in `REVIEW.md` and stay separate so this PR is reviewable.

---

## 2. Decisions already made

These were confirmed with the project owner before the plan was written. Do not relitigate them mid-execution; surface concerns first.

| Decision | Choice | Rationale |
|---|---|---|
| Workspace tool | **`uv`** with `[tool.uv.workspace]` + single `uv.lock` | Native workspace support, fast Docker installs, lockfile reproducibility, drop-in replacement for pip flows. |
| LangGraph layout | **Single top-level `apps/agents/langgraph.json`** registering both graphs | Matches LangGraph server default schema; supports a future `langgraph build` / `langgraph deploy` of just `apps/agents/` independent of FastAPI. |
| App naming | `apps/agents/` and `apps/backend/` (not `gateway`) | Owner preference. |
| Package layout inside apps | Top-level subfolders directly under `src/` (no `nalm_*` wrapper). Inside `apps/agents/src/`: `agents/` (graphs) and `services/` (clients). Inside `apps/backend/src/`: `api/`. | Owner preference. Generic top-level names (`agents`, `services`, `api`) are acceptable because nothing here is published to PyPI. |
| Shared service clients | Live inside `apps/agents/src/services/` for now. **No** separate `packages/shared-services/` workspace member. | YAGNI. Extract to a shared package only when the LangGraph server actually gets split out and the backend needs Supabase without the rest. |
| Backend → agents coupling | Today: direct import of graph + service objects via the `agents` workspace path dep. Future: HTTP via `langgraph_sdk`. | Lets us ship this PR without rewiring graph invocation. |
| GAS submodule scope | Update `gas-scripts/README.md` only (no code changes — paths stay the same). Bump submodule pointer in main repo PR. | No URL changes, no functional impact on triggers. |
| Out of scope | Q3 DI, A1/A2 checkpointer/store, A3 HITL, S1/S2 auth + CORS, H1/H2/H3 upload limits, splitting `main.py` further | Each gets its own PR after this lands. |

---

## 3. Findings from the existing code (verified during planning)

Use these as anchors when executing — they describe what's true *before* the refactor.

1. **Zero cross-agent imports.** `apps/agents/src/po_parser/` never imports from `image_tagging/` and vice versa. Verified with `grep -r "src\.image_tagging" apps/agents/src/po_parser/` (no matches) and the inverse.
2. **`po_parser/` uses `src/services/`:**
   - `airtable` — `nodes/validator.py:11-12`, `nodes/airtable_writer.py:11-12`
   - `openai` — `nodes/extract_po.py:21-22`, `nodes/classifier.py:13-14`
   - `gas_callback` — `nodes/gas_callback.py:10-11`
3. **`image_tagging/` uses NOTHING from `src/services/`.** It talks to OpenAI via `langchain_openai.ChatOpenAI` directly (`nodes/taggers.py:6`, `nodes/vision.py:6`). Verified with `grep -r "src\.services" apps/agents/src/image_tagging/` (no matches).
4. **`api/main.py` is the only place that imports `services/supabase`** (image-tagging persistence at lines 216, 268, 285, 333, 361, 407, 524) and `verify_webhook_secret` (line 23, used by `/webhook/email`).
5. **`api/main.py` lazy-imports both graphs** at request time (lines 128, 198, 397, 514). These are the only edges between the API layer and the graph layer. After the refactor, they become module-level imports from the `agents` workspace package.
6. **`uploads/`** (FastAPI `StaticFiles` mount, line 120) is used only by image-tagging endpoints. `po_parser/` is filesystem-free.
7. **Frontend** (`apps/frontend/`) only consumes image-tagging endpoints; it never hits `/webhook/email`. Confirmed by grepping the Next.js source for `/webhook/email` and `/api/po` patterns.
8. **GAS submodule** has two triggers (`gas-scripts/EmailTrigger.js`, `gas-scripts/DriveTrigger.js`) that both POST to the same FastAPI host with different paths.
9. **The `tests/` directory under `apps/agents/` contains only an empty `__init__.py`** — there are no tests to migrate or break.

---

## 4. Target layout

```
nalm-ai-agents/
├── pyproject.toml                       # uv workspace root
├── uv.lock                              # single lockfile, committed
├── docker-compose.yml                   # backend + frontend (agents image is a future build)
├── .env / .env.example                  # unchanged, shared
├── REVIEW.md                            # unchanged
├── MONOREPO_RESTRUCTURE_PLAN.md         # this document
│
├── apps/
│   ├── agents/                          # ONE LangGraph deployable, both graphs + service clients
│   │   ├── pyproject.toml               # name = "agents"; packages = ["src/agents", "src/services"]
│   │   ├── langgraph.json               # registers po_parser + image_tagging
│   │   ├── Dockerfile                   # placeholder for future `langgraph build`
│   │   └── src/
│   │       ├── agents/
│   │       │   ├── __init__.py
│   │       │   ├── po_parser/
│   │       │   │   ├── __init__.py
│   │       │   │   ├── graph.py         # was apps/agents/src/po_parser/po_parser.py
│   │       │   │   ├── graph_builder.py
│   │       │   │   ├── settings.py
│   │       │   │   ├── configuration.py
│   │       │   │   ├── utils.py
│   │       │   │   ├── nodes/           # contents unchanged
│   │       │   │   ├── prompts/
│   │       │   │   ├── schemas/
│   │       │   │   └── tools/
│   │       │   └── image_tagging/
│   │       │       ├── __init__.py
│   │       │       ├── graph.py         # was apps/agents/src/image_tagging/image_tagging.py
│   │       │       ├── graph_builder.py
│   │       │       ├── settings.py
│   │       │       ├── configuration.py
│   │       │       ├── taxonomy.py
│   │       │       ├── nodes/
│   │       │       ├── prompts/
│   │       │       ├── schemas/
│   │       │       └── tools/
│   │       └── services/                # was apps/agents/src/services/
│   │           ├── __init__.py
│   │           ├── base.py
│   │           ├── airtable/
│   │           ├── openai/
│   │           ├── supabase/
│   │           └── gas_callback/
│   │
│   ├── backend/                         # FastAPI HTTP layer
│   │   ├── pyproject.toml               # name = "backend"; packages = ["src/api"]
│   │   ├── Dockerfile
│   │   ├── uploads/                     # bind/volume mount target (gitkept, contents ignored)
│   │   └── src/
│   │       └── api/
│   │           ├── __init__.py
│   │           ├── main.py              # was `apps/agents` `src/api/main.py`
│   │           └── middleware.py        # was `apps/agents` `src/api/middleware.py`
│   │
│   └── frontend/                        # unchanged
│
├── gas-scripts/                         # submodule, README updated
├── description/                         # unchanged
└── scripts/                             # unchanged
```

### Why this layout supports the future LangGraph-server split

`apps/agents/` is a self-contained workspace member. Its `langgraph.json` lives at the package root with relative paths into `src/agents/`. That means:

- **Today:** `apps/backend/` depends on `agents` (workspace path dep) and imports both the graph objects (`from agents.po_parser.graph import graph`) and the service clients (`from services.supabase import get_client`). One Python process serves HTTP and runs graphs.
- **Tomorrow:** `apps/agents/` is built into a LangGraph server image (`langgraph build`) and run as its own service. The backend swaps the direct graph imports for HTTP calls via `langgraph_sdk.get_client()`. Whatever service clients the backend still needs (probably just Supabase) get extracted into a small `packages/shared-services/` workspace member at that point.

The directory layout doesn't have to change to support that future split. Only the backend's imports and Dockerfile do.

---

## 5. New files (full content where short, sketches where long)

### 5.1 Workspace root `pyproject.toml`

```toml
[project]
name = "nalm-ai-agents-workspace"
version = "0.0.0"
description = "Workspace root for the NALM AI Agents monorepo."
requires-python = ">=3.11"

[tool.uv.workspace]
members = [
  "apps/agents",
  "apps/backend",
]

[tool.uv.sources]
agents = { workspace = true }
```

### 5.2 `apps/agents/pyproject.toml`

```toml
[project]
name = "agents"
version = "0.0.0"
description = "LangGraph agents (PO Parser + Image Tagger) and shared service clients."
requires-python = ">=3.11"
dependencies = [
  "langgraph>=0.2",
  "langchain-core>=0.2",
  "langchain-openai>=0.1",
  "langsmith>=0.1",
  "openai>=1.0",
  "pyairtable>=2.3",
  "psycopg2-binary>=2.9",
  "httpx>=0.26",
  "pdfplumber>=0.11",
  "PyMuPDF>=1.24",
  "openpyxl>=3.1",
  "pandas>=2.0",
  "pydantic>=2.0",
  "pydantic-settings>=2.0",
  "python-dotenv>=1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agents", "src/services"]
```

> **Note for the executor:** if `hatchling` complains about two src packages without a common parent, add `[tool.hatch.build.targets.wheel.sources]` mapping `"src" = ""` so both `src/agents/` and `src/services/` get installed as top-level packages. Verify with `uv pip show agents` and `python -c "import agents.po_parser.graph; import services.supabase; print('ok')"` after sync.

### 5.3 `apps/agents/langgraph.json`

```json
{
  "graphs": {
    "po_parser":     "./src/agents/po_parser/graph.py:graph",
    "image_tagging": "./src/agents/image_tagging/graph.py:graph"
  },
  "env": "../../.env",
  "python_version": "3.11",
  "dependencies": ["."]
}
```

### 5.4 `apps/agents/Dockerfile` (placeholder)

```dockerfile
# Placeholder for future independent LangGraph server deployment.
# To produce a real image when the time comes:
#
#   cd apps/agents
#   uv run langgraph build -t agents:local
#
# The langgraph CLI generates its own image based on langgraph.json
# and the dependencies declared in pyproject.toml.
#
# This file exists today only to document the future deploy story.
FROM python:3.11-slim
LABEL org.opencontainers.image.description="Placeholder. Build with `langgraph build` instead."
```

### 5.5 `apps/backend/pyproject.toml`

```toml
[project]
name = "backend"
version = "0.0.0"
description = "FastAPI HTTP layer fronting the agents workspace package."
requires-python = ">=3.11"
dependencies = [
  "agents",
  "fastapi>=0.109",
  "uvicorn[standard]>=0.27",
  "python-multipart>=0.0.9",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/api"]
```

### 5.6 `apps/backend/Dockerfile`

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        poppler-utils \
        libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy workspace root + both members
COPY pyproject.toml uv.lock ./
COPY apps/agents  ./apps/agents
COPY apps/backend ./apps/backend

# Sync only what `backend` needs (transitively pulls in `agents`)
RUN uv sync --frozen --package backend --no-dev

# Drop privileges (REVIEW M3 fix)
RUN useradd -m -u 1000 app \
    && mkdir -p /app/apps/backend/uploads \
    && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

System packages stay because `pdfplumber` / `PyMuPDF` are pulled in transitively via `agents`. They can be dropped when the backend later flips to HTTP-only and drops the `agents` workspace dep.

### 5.7 `apps/backend/uploads/.gitkeep`

Empty file. The `uploads/` directory must exist at clone time so the Docker volume mount has a target.

### 5.8 New `__init__.py` files

Add empty `__init__.py` to:
- `apps/agents/src/agents/`
- `apps/agents/src/agents/po_parser/`
- `apps/agents/src/agents/image_tagging/`
- `apps/agents/src/services/`
- `apps/backend/src/api/`

(`po_parser/nodes/`, `prompts/`, `schemas/`, `tools/`, etc. already have `__init__.py` from the existing layout — those move with their parent dirs.)

### 5.9 `docker-compose.yml` (replaces existing)

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: apps/backend/Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - backend_uploads:/app/apps/backend/uploads
    restart: unless-stopped

  frontend:
    build:
      context: ./apps/frontend
      dockerfile: Dockerfile
      args:
        NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-http://localhost:8000}
    ports:
      - "3000:3000"
    env_file:
      - .env
    depends_on:
      - backend
    restart: unless-stopped

volumes:
  backend_uploads:
```

Notes:
- The build context becomes the repo root so the backend Dockerfile can `COPY` the workspace.
- The legacy `mock-server` profile is removed; it referenced the old `apps/agents` shape and the `scripts/test_e2e_mock.py` standalone.
- Frontend keeps `NEXT_PUBLIC_API_URL=http://localhost:8000` — the backend still owns the public surface on port 8000.

### 5.10 `.gitignore` additions

```
# uploads contents are runtime data
apps/backend/uploads/*
!apps/backend/uploads/.gitkeep
```

---

## 6. Files to delete

After the move is verified:

- `apps/agents/Dockerfile` (old)
- `apps/agents/requirements.txt`
- `apps/agents/langgraph.json` (old; replaced by the new one inside the same dir)
- `apps/agents/tests/` (empty)
- **`apps/agents` `src/api/`** (entire dir — moved to `apps/backend/src/api/`)
- `apps/agents/src/po_parser/` (entire dir — moved to `apps/agents/src/agents/po_parser/`)
- `apps/agents/src/image_tagging/` (entire dir — moved to `apps/agents/src/agents/image_tagging/`)
- `apps/agents/src/__init__.py` (no longer a top-level package; `agents/` and `services/` become the top-level packages instead)

---

## 7. Import rewrites (sed-able)

Apply these rewrites consistently across the codebase. Run a final `grep -r "src\." apps/` and confirm no legacy **src.po_parser**, **src.image_tagging**, **src.services**, or **src.api** roots remain except under migration notes.

| Old (import path) | New | Where it appears |
|---|---|---|
| `src.services.airtable` | `services.airtable` | po_parser nodes (validator, airtable_writer) |
| `src.services.openai` | `services.openai` | po_parser nodes (extract_po, classifier) |
| `src.services.supabase` | `services.supabase` | backend `api/main.py` |
| `src.services.gas_callback` | `services.gas_callback` | po_parser nodes (gas_callback), backend `api/main.py` |
| `src.services.base` | `services.base` | wherever shared base config is referenced |
| `src.api.middleware` (`verify_webhook_secret`) | `api.middleware` | backend `api/main.py` |
| `src.po_parser.po_parser` graph entry | `agents.po_parser.graph` | backend `api/main.py:128` |
| `src.po_parser.schemas.email` (`IncomingEmail`) | `agents.po_parser.schemas.email` | backend `api/main.py:24` |
| `src.po_parser.*` (intra-package, inside po_parser nodes) | `agents.po_parser.*` | po_parser internal imports |
| `src.image_tagging.image_tagging` graph entry | `agents.image_tagging.graph` | backend `api/main.py:198, 397, 514` |
| `src.image_tagging.taxonomy` (`TAXONOMY`) | `agents.image_tagging.taxonomy` | backend `api/main.py:175` |
| `src.image_tagging.*` (intra-package, inside image_tagging nodes) | `agents.image_tagging.*` | image_tagging internal imports |

> **Watch out for this:** the lazy in-handler imports inside `apps/agents` `src/api/main.py` (lines 128, 198, 216, 268, 333, 397, 407, 514, 524, 541, 561) all need rewriting too. We are intentionally NOT converting them to module-level imports or `Depends`-DI in this PR — that's REVIEW Q3 and gets its own pass. Just rewrite the **src.*** package prefix and leave them where they are.

> **Top-level package name collision risk:** `agents`, `services`, and `api` are generic. Double-check that no transitive Python dep ships a top-level package with one of these names. As of writing, none of the deps in `requirements.txt` do. If a future dep collides, we'll need a `nalm_*` prefix; not blocking today.

---

## 8. Step-by-step execution

Each numbered step is intended to be its own commit so the migration is bisectable. The working tree must be runnable at the end of every step.

### Step 1 — Scaffold the workspace

**Goal:** Add the workspace root files without moving any code yet.

1. Create `pyproject.toml` at the repo root with the contents from §5.1, but with an **empty** `members = []` list initially.
2. Run `uv sync` from the repo root. Expect it to succeed and produce a no-op `uv.lock`. Commit the lockfile.
3. Verify nothing else changed: `git status` should show only `pyproject.toml` and `uv.lock`.

**Commit:** `chore(workspace): scaffold uv workspace root`

### Step 2 — Stage the new agents layout under `apps/agents-new/`

**Goal:** Build the new `apps/agents/` shape without disturbing the running app. We use a temporary `apps/agents-new/` so the old tree keeps working.

1. Create `apps/agents-new/pyproject.toml` per §5.2.
2. Create `apps/agents-new/langgraph.json` per §5.3.
3. Create `apps/agents-new/Dockerfile` per §5.4.
4. **Move source files** (use `git mv` so history is preserved):
   - `git mv apps/agents/src/po_parser apps/agents-new/src/agents/po_parser`
   - `git mv apps/agents/src/image_tagging apps/agents-new/src/agents/image_tagging`
   - `git mv apps/agents/src/services apps/agents-new/src/services`
5. **Rename graph entry files:**
   - `git mv apps/agents-new/src/agents/po_parser/po_parser.py apps/agents-new/src/agents/po_parser/graph.py`
   - `git mv apps/agents-new/src/agents/image_tagging/image_tagging.py apps/agents-new/src/agents/image_tagging/graph.py`
6. **Add new `__init__.py` files** per §5.8 (the ones for `agents/` and `services/`).
7. **Rewrite imports** inside `apps/agents-new/src/` per §7. Quick way to find them all:
   ```
   grep -rn "src\." apps/agents-new/src/
   ```
   Replace each match according to the table.
8. Add `apps/agents-new` to the workspace `members` list in the root `pyproject.toml`.
9. Run `uv sync`. Expect it to install the `agents` package successfully.
10. Smoke-test imports:
    ```
    uv run python -c "from agents.po_parser.graph import graph; print(graph)"
    uv run python -c "from agents.image_tagging.graph import graph; print(graph)"
    uv run python -c "from services.supabase import get_client, SUPABASE_ENABLED; print(SUPABASE_ENABLED)"
    ```
    All three must succeed without errors.
11. Smoke-test the LangGraph CLI against the new layout:
    ```
    cd apps/agents-new && uv run langgraph dev
    ```
    Both graphs (`po_parser`, `image_tagging`) should appear in LangGraph Studio. Stop the server.

> **Important:** at this point the old **`apps/agents` `src/api/`** tree still exists and still references the old `src.po_parser.*` paths. Those will fail to import because we just moved the source. **The old gateway is broken between Step 2 and Step 3.** That's intentional and expected — we keep this window short by doing Steps 2 and 3 back-to-back.

**Commit:** `refactor(agents): stage new agents layout under agents-new/`

### Step 3 — Create `apps/backend/`

**Goal:** Move the FastAPI layer out of **`apps/agents` `src/api/`** into `apps/backend/`.

1. Create `apps/backend/pyproject.toml` per §5.5.
2. Create `apps/backend/Dockerfile` per §5.6.
3. Create `apps/backend/uploads/.gitkeep` per §5.7.
4. Add the `.gitignore` entries from §5.10.
5. **Move source files** (FastAPI was under **`apps/agents`** in **`src/api/`**; destination is `apps/backend/src/api/`):
   - `git mv` **`main.py`** from the historical **`src/api`** folder inside **`apps/agents`** to `apps/backend/src/api/main.py` (full source path is three segments: **apps/agents**, **src/api**, **main.py**).
   - Same for **`middleware.py`** → `apps/backend/src/api/middleware.py`.
6. Add `apps/backend/src/api/__init__.py` (empty).
7. **Rewrite imports** in `apps/backend/src/api/main.py` and `middleware.py` per §7. Pay attention to:
   - The lazy in-handler imports at `main.py:128, 198, 216, 268, 333, 397, 407, 514, 524, 541, 561` — rewrite each **src.*** import prefix in place.
   - The top-of-file import of **`api.middleware`** (`verify_webhook_secret`) (line 23) becomes `from api.middleware import verify_webhook_secret` (replacing the old **src.api** path).
   - The top-of-file import of **`agents.po_parser.schemas.email`** (`IncomingEmail`) (line 24) becomes `from agents.po_parser.schemas.email import IncomingEmail` (replacing the old **src.po_parser** path).
   - The `UPLOADS_DIR` path (line 33) previously resolved to **`apps/agents` `uploads/`** via `Path(__file__).resolve().parent.parent.parent / "uploads"`. The new file lives at `apps/backend/src/api/main.py`, so the same relative chain (`parent.parent.parent`) now resolves to `apps/backend/uploads/`. **Verify this calculation matches.** If hatch installs the wheel into a different layout at runtime, fall back to an explicit env var (`UPLOADS_DIR=/app/apps/backend/uploads`) read at startup.
8. Add `apps/backend` to the workspace `members` list in the root `pyproject.toml`.
9. Run `uv sync`. The `backend` package should install and pull `agents` as a workspace dep.
10. Smoke-test the backend locally (without Docker):
    ```
    uv run --package backend uvicorn api.main:app --port 8000
    ```
    Then in another shell:
    ```
    curl localhost:8000/health
    curl localhost:8000/api/taxonomy
    ```
    Both should return 200. Stop uvicorn.

**Commit:** `refactor(backend): extract FastAPI layer into apps/backend/`

### Step 4 — Delete the old `apps/agents/` tree and promote `apps/agents-new/`

**Goal:** Cut over to the final layout.

1. Verify the old tree has nothing left under `apps/agents/src/` (only `__init__.py` should remain after Steps 2 and 3).
2. Delete remnants:
   ```
   rm apps/agents/Dockerfile
   rm apps/agents/requirements.txt
   rm apps/agents/langgraph.json
   rm -r apps/agents/tests
   rm -r apps/agents/src   # only __init__.py left
   rmdir apps/agents
   ```
3. Rename the staging dir:
   ```
   git mv apps/agents-new apps/agents
   ```
4. Update the workspace `members` list in the root `pyproject.toml`: replace `"apps/agents-new"` with `"apps/agents"`.
5. Run `uv sync` again to refresh the lockfile with the new path. Commit `uv.lock`.
6. Final sanity grep:
   ```
   grep -rn "src\." apps/
   grep -rn "import src\." apps/
   grep -rn "apps/agents-new" .
   ```
   All three must return zero matches.
7. Re-run the local backend smoke test from Step 3.10 to confirm nothing regressed across the rename.

**Commit:** `refactor(monorepo): promote apps/agents-new to apps/agents and delete legacy tree`

### Step 5 — Rewrite `docker-compose.yml`

**Goal:** Make the containers reflect the new layout.

1. Replace `docker-compose.yml` with the contents from §5.9.
2. Build:
   ```
   docker compose build
   ```
3. Bring up:
   ```
   docker compose up
   ```
4. Smoke-test inside the running stack:
   - `curl localhost:8000/health`
   - `curl localhost:8000/api/taxonomy`
   - Upload a small JPEG via `curl -F "file=@sample.jpg" localhost:8000/api/analyze-image` and verify a JSON response with `tags_by_category`.
   - Verify the file landed in the `backend_uploads` named volume (or in `apps/backend/uploads/` if you swap the named volume for a bind mount).
5. Verify the backend container runs as a non-root user:
   ```
   docker compose exec backend whoami      # should print "app", not "root"
   ```

**Commit:** `chore(docker): rewrite docker-compose for backend + future agents layout`

### Step 6 — Update `.env.example` and `README.md`

**Goal:** Documentation matches reality.

1. **`.env.example`:** confirm `NEXT_PUBLIC_API_URL=http://localhost:8000` is still present and points at the backend. Remove any env vars that referenced the old `apps/agents` shape (none expected, but double-check).
2. **`README.md`:**
   - Replace the "agents service" section with two sections: "Agents (LangGraph)" describing `apps/agents/` and the future `langgraph build` story; "Backend (FastAPI)" describing `apps/backend/` and the route surface.
   - Update the Quick Start commands to use `uv`:
     ```
     uv sync
     uv run --package backend uvicorn api.main:app --port 8000
     ```
   - Update the LangGraph Studio section: `cd apps/agents && uv run langgraph dev`.
   - Update the directory tree at the top of the README to match §4 of this plan.
   - Add a note that the LangGraph server can be deployed independently in the future via `langgraph build` against `apps/agents/langgraph.json`.

**Commit:** `docs: update README and env example for new monorepo layout`

### Step 7 — GAS submodule

**Goal:** Keep the submodule docs honest.

1. In the `gas-scripts/` submodule, edit `gas-scripts/README.md`: refresh the architecture diagram to show `apps/backend` (instead of `apps/agents`) as the FastAPI host. Mention that both webhook URLs still resolve to the same backend host today, and that they may point at a separately-deployed LangGraph server in the future.
2. **No code changes** in `Config.gs`, `EmailTrigger.js`, or `DriveTrigger.js`. URLs and payloads are unchanged.
3. Commit the submodule change inside the submodule and push to its remote.
4. In the main repo, bump the submodule pointer:
   ```
   git add gas-scripts
   git commit -m "chore: bump gas-scripts submodule for README refresh"
   ```

### Step 8 — End-to-end verification

Run the full Verification checklist from §10 below before opening the PR.

---

## 9. What we are NOT doing in this PR

Each of these is tracked in `REVIEW.md` and gets its own PR. Do not let scope creep in.

- **Q2 / Q10** — splitting `backend/api/main.py` further into route modules + a service layer. The file gets relocated and import-rewritten only.
- **Q3** — converting the lazy in-handler service imports in `main.py` to FastAPI `Depends` DI.
- **A1, A2** — wiring `PostgresSaver` checkpointer and `PostgresStore` for memory.
- **A3** — adding the `interrupt()` HITL gate before Airtable writes.
- **S1, S2** — restricting CORS and adding auth dependencies. The `allow_origins=["*"]` line gets carried over verbatim.
- **H1, H2, H3** — upload size limits, magic-number validation, and base64 size caps.
- **Flipping the backend from direct graph imports to HTTP** against a separately-deployed LangGraph server. This plan **enables** that future move; it doesn't make it.
- **Extracting service clients into a separate `packages/shared-services/`** workspace member. Defer until the LangGraph server actually gets split out and the backend stops needing the rest of `agents`.

If any of these feel tempting while you're in the code, resist. They each deserve their own focused review.

---

## 10. Verification checklist

Run all of these before requesting review. Tick each box in the PR description.

### Workspace + import sanity

- [ ] `uv sync` from the repo root succeeds with no warnings.
- [ ] `uv.lock` is committed and unchanged after a second `uv sync` (lockfile is stable).
- [ ] `grep -rn "src\." apps/` returns zero matches.
- [ ] `grep -rn "import src\." apps/` returns zero matches.
- [ ] `grep -rn "apps/agents-new" .` returns zero matches.
- [ ] `apps/agents/src/` contains exactly two top-level dirs: `agents/` and `services/`.
- [ ] `apps/backend/src/` contains exactly one top-level dir: `api/`.
- [ ] Old files are gone: `apps/agents/Dockerfile`, `apps/agents/requirements.txt`, `apps/agents/tests/`, **`apps/agents` `src/api/`**, `apps/agents/src/po_parser/`, `apps/agents/src/image_tagging/`.

### Local dev (no Docker)

- [ ] `uv run --package backend uvicorn api.main:app --port 8000` boots cleanly.
- [ ] `curl localhost:8000/health` returns `{"status":"healthy", ...}`.
- [ ] `curl localhost:8000/api/taxonomy` returns the taxonomy JSON.
- [ ] `cd apps/agents && uv run langgraph dev` boots LangGraph Studio with both graphs visible.

### Docker

- [ ] `docker compose build` succeeds.
- [ ] `docker compose up` starts both services; ports 8000 and 3000 are reachable.
- [ ] `docker compose exec backend whoami` returns `app` (not `root`). This locks in REVIEW M3.
- [ ] `curl localhost:8000/health` from the host returns 200.

### Smoke tests

- [ ] **PO parser:** `POST /webhook/email` with a sample `IncomingEmail` JSON body and the correct `X-Webhook-Secret` header. Verify the background task runs (logs show classifier → extractor → validator → writer), Airtable record is created (or skipped cleanly if Airtable env vars are absent), no import errors.
- [ ] **Image tagger:** `POST /api/analyze-image` with a small JPEG. Verify the file lands at the expected uploads location, the response includes `tags_by_category`, the Supabase row is created (or skipped cleanly if Supabase env vars are absent).
- [ ] **Frontend:** open `http://localhost:3000`, upload an image via the UI, confirm the result renders with tags.
- [ ] **GAS triggers:** in the Apps Script editor, manually run `EmailTrigger.run()` and `DriveTrigger.run()`. Both should reach the backend and log success.

### Git hygiene

- [ ] Each step from §8 is its own commit.
- [ ] `git log --oneline` shows the migration is bisectable.
- [ ] `git mv` was used for source file moves so blame history is preserved.
- [ ] No commits skip hooks (no `--no-verify`).

---

## 11. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `hatchling` rejects the two-package wheel layout (`packages = ["src/agents", "src/services"]`) | Medium | Blocks Step 2.9 | Add `[tool.hatch.build.targets.wheel.sources] "src" = ""` mapping. If still broken, fall back to `setuptools` with `[tool.setuptools.packages.find] where = ["src"]`. |
| `UPLOADS_DIR` path calculation in `main.py` breaks after the move (the `parent.parent.parent` chain resolves to a different location) | Medium | Breaks `/api/analyze-image` and `/uploads` static mount | After Step 3, run `uv run python -c "from api.main import UPLOADS_DIR; print(UPLOADS_DIR)"` and verify it's `apps/backend/uploads/`. If wrong, replace the path calculation with an env-var-driven absolute path. |
| Top-level package name collision (`agents`, `services`, `api`) with a future transitive dep | Low | Import shadowing | Reserved as a known issue. Switch to `nalm_*` prefix if it ever happens. |
| LangGraph Studio fails to load the new layout because `langgraph.json` paths are wrong | Low | Step 2.11 fails | Verify the relative paths in `langgraph.json` match the new layout exactly (`./src/agents/po_parser/graph.py:graph`). |
| Lazy in-handler imports in `main.py` get rewritten incorrectly because there are 11 of them at scattered line numbers | Medium | Runtime `ImportError` on first request to a route | After rewriting, run `python -m py_compile apps/backend/src/api/main.py` and then exercise every endpoint in the smoke tests. |
| `psycopg2-binary` wheel install fails inside Docker because of missing `libpq` headers | Low | Backend image build fails | The Dockerfile already installs `libpq-dev`. If it still fails, switch to `psycopg[binary]` (psycopg3) which ships static binaries. |
| Frontend can't reach the backend after the rename because Docker Compose service name changed from `agents` to `backend` | Low | Frontend network errors | The frontend uses `NEXT_PUBLIC_API_URL` (resolved at build time), not the Compose service name, so this should be fine. Verify with the smoke test in §10. |
| Old **`apps/agents` `src/api/`** tree is deleted before `apps/backend/` is wired up, leaving the working tree broken between Step 2 and Step 3 | High | Broken main between commits | Sequence Steps 2 and 3 in the same PR review cycle. Do not push Step 2 to main alone. |

---

## 12. Rollback plan

If something goes wrong after merging:

1. **Revert the merge commit.** All steps were committed against the main branch through the PR; reverting the merge restores the old layout in a single commit.
2. **`git submodule update --init gas-scripts`** to restore the submodule pointer if it was bumped.
3. Rebuild containers from the old `docker-compose.yml`: `docker compose build && docker compose up`.

Because no business logic changed, a revert is safe and complete. There is no data migration to roll back.

---

## 13. Open follow-ups (post-merge)

In rough priority order. Each is its own PR.

1. **Wire `langgraph build`** against `apps/agents/langgraph.json` and verify the produced image runs the graphs end-to-end. This is the proof that the future split is real.
2. **Address REVIEW Q2 / Q10:** split `apps/backend/src/api/main.py` into `routes/{po,images,health}.py` + a thin `services/image_pipeline.py`.
3. **Address REVIEW Q3:** convert the in-handler service imports to FastAPI `Depends` DI.
4. **Address REVIEW S1 / S2:** explicit CORS allowlist and auth dependency on the image data endpoints.
5. **Address REVIEW A1 / A2 / A3:** wire `PostgresSaver` checkpointer, `PostgresStore` for memory, and the HITL `interrupt()` gate before Airtable writes.
6. **When ready, flip the backend** from direct graph imports to HTTP via `langgraph_sdk.get_client()`. At that point, extract Supabase into `packages/shared-services/` and drop the `agents` workspace dep + the PO-extractor system packages from the backend image.

---

## Appendix A — Cheat sheet of commands the executor will run

```bash
# Workspace install
uv sync

# Local dev — backend
uv run --package backend uvicorn api.main:app --port 8000

# Local dev — LangGraph Studio
cd apps/agents && uv run langgraph dev

# Smoke imports after Step 2
uv run python -c "from agents.po_parser.graph import graph; print(graph)"
uv run python -c "from agents.image_tagging.graph import graph; print(graph)"
uv run python -c "from services.supabase import get_client; print(get_client)"

# Find leftover legacy imports
grep -rn "src\." apps/
grep -rn "import src\." apps/

# Docker
docker compose build
docker compose up
docker compose exec backend whoami       # expect: app

# Smoke tests
curl localhost:8000/health
curl localhost:8000/api/taxonomy
curl -F "file=@sample.jpg" localhost:8000/api/analyze-image
```

## Appendix B — Files referenced from REVIEW.md

This plan touches every file flagged structurally in `REVIEW.md`. For traceability:

| REVIEW item | File(s) | How this plan touches them |
|---|---|---|
| Q2 (god file) | `apps/agents` `src/api/main.py` | Relocated to `apps/backend/src/api/main.py`. Internal split deferred. |
| Q3 (in-handler imports) | `apps/agents` `src/api/main.py:128,198,216,268,333,397,407,514,524,541,561` | Rewritten in place. Conversion to `Depends` deferred. |
| §6 (service layer / repository pattern / DI) | All of `apps/agents/src/services/` | Relocated to `apps/agents/src/services/` (new shape). Pattern adoption deferred. |
| §9 (monorepo separation) | Whole repo | This plan **is** the §9 implementation. |
| M3 (root container) | `apps/agents/Dockerfile` | Replaced by `apps/backend/Dockerfile` which drops privileges to `app`. |
| H5 (BATCH_STORAGE) | `apps/agents` `src/api/main.py:39` | Carried over verbatim. Replacement with checkpointer-backed state deferred. |

---

*End of plan.*
