# Phase 1 — Monorepo Scaffold & Tooling

## Objective

Create the empty but correct project skeleton: a `uv` workspace with `apps/agents`, `apps/backend`, `apps/frontend` (frontend is just a placeholder folder this phase), plus linting/formatting/type-checking tooling and env files. **No app logic yet.** By the end, `uv sync` and `uv run ruff check .` succeed.

## Prerequisites

- Windows + PowerShell, in the repo root `c:\Nagdy\Mustafa\Upwork\Demo-Project-1`.
- Installed: `uv` (`uv --version`), Python 3.11+ (`uv python install 3.11`), Docker Desktop, Git.
- A root `.env` already exists. Do not overwrite it; only add missing keys.

## Steps

### 1. Root workspace `pyproject.toml`

Create `pyproject.toml` at the repo root:

```toml
[project]
name = "reel-workspace"
version = "0.0.0"
description = "GraphRAG Movie Agent monorepo (Reel)."
requires-python = ">=3.11"

[tool.uv]
package = false

[tool.uv.workspace]
members = ["apps/agents", "apps/backend"]

[tool.uv.sources]
agents = { workspace = true }

[dependency-groups]
dev = [
  "ruff>=0.6",
  "pyright>=1.1.380",
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "pre-commit>=3.8",
]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["apps/agents/src", "apps/backend/src"]

[tool.ruff.lint]
# E/F=pyflakes+pycodestyle, I=isort, UP=pyupgrade, D=pydocstyle (mandatory docstrings), B=bugbear, ASYNC
select = ["E", "F", "I", "UP", "D", "B", "ASYNC"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["D"]        # tests still get docstrings via testing rule, but do not fail CI on missing package docstrings
"**/__init__.py" = ["D104"]  # allow empty package docstring on __init__ if truly empty

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "basic"
include = ["apps/agents/src", "apps/backend/src"]
```

Notes for the implementer:
- `package = false` marks the root as a non-installable workspace container.
- Keep the `D` (docstring) rule enabled — it is a project requirement.

### 2. `apps/agents` package

Create `apps/agents/pyproject.toml`:

```toml
[project]
name = "agents"
version = "0.0.0"
description = "LangGraph GraphRAG movie agent."
requires-python = ">=3.11"
dependencies = [
  "langgraph>=1.2",
  "langgraph-checkpoint-postgres>=2.0",
  "langchain-core>=0.3",
  "langchain-openai>=0.2",
  "langsmith>=0.1",
  "neo4j>=5.24",
  "neo4j-graphrag[openai]>=1.0",
  "pydantic>=2",
  "pydantic-settings>=2",
  "python-dotenv>=1",
  "tenacity>=9",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agents", "src/ingestion"]
```

Create these empty package files (each is a real Python package, so each needs an `__init__.py` with a one-line module docstring):

- `apps/agents/src/agents/__init__.py`
  ```python
  """Reel LangGraph agent package."""
  ```
- `apps/agents/src/ingestion/__init__.py`
  ```python
  """Neo4j data ingestion for the Reel movie graph."""
  ```

Create `apps/agents/tests/__init__.py`:
```python
"""Tests for the agents package."""
```

> The real graph, nodes, tools, settings, ingestion, `langgraph.json`, and `Dockerfile` are added in later phases. Do NOT create them now.

### 3. `apps/backend` package

Create `apps/backend/pyproject.toml`:

```toml
[project]
name = "backend"
version = "0.0.0"
description = "FastAPI HTTP layer for the Reel agent."
requires-python = ">=3.11"
dependencies = [
  "agents",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2",
  "pydantic-settings>=2",
  "pyjwt[crypto]>=2.9",
  "httpx>=0.27",
  "slowapi>=0.1.9",
  "python-json-logger>=2.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/api"]
```

Create:
- `apps/backend/src/api/__init__.py`
  ```python
  """Reel FastAPI application package."""
  ```
- `apps/backend/tests/__init__.py`
  ```python
  """Tests for the backend package."""
  ```

### 4. Frontend placeholder

Create the folder `apps/frontend/` with a placeholder `apps/frontend/.gitkeep` (empty file). The full Next.js app is created in Phase 8.

### 5. Tooling files

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-yaml
```

Create `.gitignore` (append if it exists):

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
# Env & secrets
.env
!.env.example
# Node
node_modules/
.next/
# OS
.DS_Store
```

### 6. `.env.example`

Create `.env.example` documenting every variable (names + comments only, NO real values). This is the full set the project will use across phases:

```dotenv
# ---- OpenAI ----
OPENAI_API_KEY=            # OpenAI API key (required)
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_EMBED_MODEL=text-embedding-3-large

# ---- LangSmith (tracing) ----
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=         # LangSmith API key (lsv2_...)
LANGSMITH_PROJECT=reel-agent

# ---- Neo4j ----
NEO4J_URI=bolt://localhost:7687     # local Docker; Aura uses neo4j+s://...
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=please-change-me
NEO4J_DATABASE=neo4j

# ---- Supabase (auth + Postgres for checkpointer/store) ----
SUPABASE_URL=              # https://<project-ref>.supabase.co
SUPABASE_JWT_AUD=authenticated
SUPABASE_DB_URL=           # postgresql://... (used by LangGraph checkpointer/store)

# ---- Backend ----
CORS_ALLOW_ORIGINS=http://localhost:3000
APP_ENV=dev                # dev | prod

# ---- LLM safety ----
LLM_TIMEOUT_SECONDS=30
LLM_MAX_TOKENS=1024
```

Then ensure the real root `.env` has at least `OPENAI_API_KEY`, `LANGSMITH_API_KEY`, and Neo4j vars for later phases. Do not commit `.env`.

### 7. Sync & verify

Run in PowerShell from the repo root:

```powershell
uv sync
uv run ruff check .
uv run ruff format --check .
```

Commit `uv.lock` (it is generated by `uv sync`).

## Environment variables

Only `.env.example` is authored here; real values live in `.env` (already present / to be filled by the user).

## Acceptance criteria

- [ ] `uv sync` completes without error and creates/updates `uv.lock`.
- [ ] `uv run python -c "import agents; import ingestion; print('ok')"` prints `ok`.
- [ ] `uv run ruff check .` passes (no errors).
- [ ] Folder layout matches: `apps/agents/src/{agents,ingestion}`, `apps/backend/src/api`, `apps/frontend/`.
- [ ] `.env.example` exists and documents every variable; `.env` is gitignored.

## Do NOT

- Do NOT create `langgraph.json`, graph code, FastAPI app, or Dockerfiles yet.
- Do NOT put any app code outside `apps/`.
- Do NOT disable the ruff `D` (docstring) rule.

## Relevant rules & skills

- Rules: `project-structure`, `documentation`, `python-standards`.
- Skill: `verify-standards` (run it at the end).
