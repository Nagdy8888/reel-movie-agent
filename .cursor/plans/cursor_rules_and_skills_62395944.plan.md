---
name: Cursor Rules and Skills
overview: Create the Cursor rules (.cursor/rules/*.mdc) and skills (.cursor/skills/*/SKILL.md) that encode the GraphRAG Movie Agent project's structure, mandatory-docstring, security, and code-quality standards — so all subsequent implementation auto-follows them. Execute this before scaffolding the project.
todos:
  - id: rules-always
    content: "Create always-apply rules: .cursor/rules/project-structure.mdc, documentation.mdc, security.mdc"
    status: completed
  - id: rules-python
    content: Create python-standards.mdc (globs apps/agents+apps/backend .py), fastapi-backend.mdc (apps/backend), langgraph-agent.mdc (apps/agents)
    status: completed
  - id: rules-frontend
    content: Create frontend.mdc (globs apps/frontend/**/*.{ts,tsx}) referencing Stitch DESIGN.md tokens
    status: completed
  - id: rules-testing
    content: Create testing.mdc (globs apps/**/tests + test_*.py) - pytest + pytest-asyncio, app.dependency_overrides, mocked OpenAI/Neo4j, pure-function coverage
    status: completed
  - id: skill-route
    content: Create .cursor/skills/add-api-route/SKILL.md (schema -> deps -> thin route -> contract test workflow)
    status: completed
  - id: skill-node
    content: Create .cursor/skills/add-agent-node/SKILL.md (contract docstring -> TypedDict update -> RetryPolicy -> wire -> test -> Studio check)
    status: completed
  - id: skill-stitch
    content: Create .cursor/skills/port-stitch-screen/SKILL.md (read code.html + screen.png -> ensure DESIGN.md tokens in tailwind config -> next/font -> split into React components/route -> replace mock data with hooks/props -> verify)
    status: completed
  - id: skill-verify
    content: Create .cursor/skills/verify-standards/SKILL.md (ruff+D, ruff format, pyright, pytest, structure + docstring gate)
    status: completed
isProject: false
---

# Cursor Rules and Skills — Setup Plan

Companion to the `GraphRAG Movie Agent` plan. Creates the dev-experience tooling (8 rules + 4 skills) that enforce the agreed standards. **Do this first**, before any project scaffolding, so every later step is guided automatically.

All content is derived from the standards captured in the main plan and the prior QA reviews (`prev-review/`). Each rule stays under ~50 lines (one concern per rule); each skill under 500 lines with concrete steps.

## Files to create

```text
.cursor/
├── rules/
│   ├── project-structure.mdc     # alwaysApply
│   ├── documentation.mdc         # alwaysApply
│   ├── security.mdc              # alwaysApply
│   ├── python-standards.mdc      # globs: apps/agents/**/*.py, apps/backend/**/*.py
│   ├── fastapi-backend.mdc       # globs: apps/backend/**/*.py
│   ├── langgraph-agent.mdc       # globs: apps/agents/**/*.py
│   ├── frontend.mdc              # globs: apps/frontend/**/*.{ts,tsx}
│   └── testing.mdc               # globs: apps/**/tests/**/*.py, apps/**/test_*.py
└── skills/
    ├── add-api-route/SKILL.md
    ├── add-agent-node/SKILL.md
    ├── port-stitch-screen/SKILL.md
    └── verify-standards/SKILL.md
```

## Rules — content spec

Each `.mdc` has YAML frontmatter (`description`, plus `alwaysApply: true` OR `globs:`) then concise, example-driven body.

- **project-structure.mdc** (`alwaysApply: true`): uv-workspace monorepo under `apps/{agents,backend,frontend}`; `agents` = LangGraph deployable (owns `langgraph.json` -> `src/agents/graph.py:graph`); `backend` = FastAPI, declares `agents` as workspace dep and imports the compiled graph; `frontend` = Next.js. State where each file type belongs; forbid god files and cross-app leakage.
- **documentation.mdc** (`alwaysApply: true`): every module/class/function/method has a docstring (ruff `D`, Google convention) — undocumented code fails lint; LangGraph nodes use the contract docstring (reads/writes/side effects/failure mode); `Field(description=...)` on all Pydantic + settings fields; keep `docs/` (C4) and `docs/setup/*` in sync with behavior changes.
- **security.mdc** (`alwaysApply: true`): agent uses a READ-ONLY Neo4j role; reject Text2Cypher output containing write clauses (`CREATE|MERGE|DELETE|SET|REMOVE|DROP|CALL`-writes); `hmac.compare_digest` for secrets; `timeout=` + `max_tokens` on every LLM call; never log secrets/PII; explicit CORS allowlist (no `*`+credentials); validate required env at startup; generic 500 bodies (no `str(exc)`).
- **python-standards.mdc** (`globs: apps/agents/**/*.py,apps/backend/**/*.py`): DI via `Depends`, no in-handler/lazy imports; one `Settings(BaseSettings)` per app (no scattered `os.getenv`); `lru_cache`'d + pooled clients (LLM, Neo4j driver, Postgres pool) — never per-call; async correctness (`await asyncio.sleep`, `asyncio.Lock`, `gather`+`Semaphore`, never `threading.Lock` across `await`); `tenacity` retries w/ jitter; `X | None` (ruff `UP007`); type hints on public signatures.
- **fastapi-backend.mdc** (`globs: apps/backend/**/*.py`): thin routes calling injected services; `response_model=` on every route; auth dependency at router level; rate-limit `/chat`; `/health` (liveness) + `/ready` (deps check); build graph eagerly in `lifespan`; request-ID + structured logging middleware.
- **langgraph-agent.mdc** (`globs: apps/agents/**/*.py`): node contract docstring; per-node `TypedDict` state update + documented reducers; `RetryPolicy` per node; compile with `PostgresSaver` checkpointer + `PostgresStore`; versioned prompt files (no inline strings); wrap runs with `run_name`/`tags`/`metadata` for LangSmith; fail-closed on retrieval/generation errors.
- **frontend.mdc** (`globs: apps/frontend/**/*.{ts,tsx}`): Next.js App Router + functional components + custom hooks; Supabase auth client; typed SSE client to backend `/chat`; use Tailwind tokens ported from Stitch `DESIGN.md` (noir + gold, Playfair/Inter) — no hardcoded hex; keep components small and colocated.
- **testing.mdc** (`globs: apps/**/tests/**/*.py,apps/**/test_*.py`): `pytest` + `pytest-asyncio`; route contract tests via `app.dependency_overrides` (stub the graph); mock external services (OpenAI, Neo4j) — no live network in unit tests; prioritize pure-function coverage (Cypher-safety validator, prompt builders, reducers); arrange-act-assert; each test has a docstring stating what it verifies.

## Skills — content spec

Each `skill-name/SKILL.md` has frontmatter (`name`, third-person `description` with WHAT+WHEN). Default `disable-model-invocation: true` unless auto-invocation is desired.

- **add-api-route**: step workflow — (1) define request/response Pydantic models in `schemas.py` with `Field(description=)`; (2) add provider(s) in `deps.py`; (3) thin handler in `routes/` with `response_model=`, auth dep, rate limit, docstring; (4) register router; (5) add route contract test using `app.dependency_overrides`; (6) run `verify-standards`.
- **add-agent-node**: step workflow — (1) write node fn with contract docstring; (2) define its `TypedDict` update + reducer if accumulating; (3) add `RetryPolicy` and wire edges in `graph.py`; (4) versioned prompt file if it calls the LLM (with `timeout`/`max_tokens`); (5) unit/fixture test; (6) confirm it renders in `langgraph dev` Studio; (7) run `verify-standards`.
- **port-stitch-screen**: step workflow to convert a Stitch export screen into the Next.js app — (1) read the target `stitch_reel_ai_movie_assistant/<screen>/code.html` and view its `screen.png`; (2) ensure design tokens from `cinematic_intelligence_system/DESIGN.md` are in `tailwind.config.ts` (port once); (3) load fonts via `next/font` (Inter, Playfair Display) + Material Symbols; (4) break the HTML into small React components under `components/` and a route under `app/`, replacing static Tailwind markup with JSX and mapping repeated blocks to props; (5) replace mock content with real data hooks / props (chat messages, sources, graph nodes); (6) keep tokens — no hardcoded hex; (7) run `verify-standards` (frontend: `pnpm lint`/`tsc`). Trigger when porting or updating any Stitch-generated screen. Notes the standing `frontend.mdc` rule for token usage.
- **verify-standards**: "definition of done" gate — run `uv run ruff check` (incl. `D`) + `uv run ruff format --check`, `uv run pyright`, `uv run pytest`; confirm files live in the correct `apps/*` location; explicitly fail if any function lacks a docstring. Emits a short pass/fail checklist.

## Notes

- Windows environment: reference paths with forward slashes inside skills.
- These files are independent of project code, so they can be created into an otherwise-empty repo now and will take effect immediately for subsequent work.
- After creation, a quick sanity check: open a would-be `apps/backend/**/*.py` path context and confirm the relevant rules surface.
