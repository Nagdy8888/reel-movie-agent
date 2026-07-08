# Phase 7 — Tests (Unit + Route Contract)

## Objective

Add a `pytest` suite that runs fast with **no live network** (no real OpenAI/Neo4j/Supabase):
- **Unit tests** for pure functions: the Cypher-safety validator and prompt builders.
- **Route contract tests** for the backend using `app.dependency_overrides` to stub the graph and auth, exercised with `httpx.AsyncClient`.
- Cover error paths (auth failure, unsafe Cypher), not just the happy path.

## Prerequisites

- Phases 4–6 complete.
- Dev deps installed (`pytest`, `pytest-asyncio` from Phase 1). Add `httpx` (already a backend dep).

## Steps

### 1. Pytest config — root `pyproject.toml`

Add:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["apps/agents/tests", "apps/backend/tests"]
```

### 2. Agent unit tests — `apps/agents/tests/test_safety.py`

```python
"""Tests for the read-only Cypher validator."""

import pytest

from agents.safety import UnsafeCypherError, ensure_read_only


def test_allows_read_only_match() -> None:
    """A plain MATCH query passes unchanged."""
    q = "MATCH (m:Movie) RETURN m.title LIMIT 5"
    assert ensure_read_only(q) == q


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (m) DETACH DELETE m",
        "CREATE (m:Movie {title: 'x'})",
        "MATCH (m:Movie) SET m.title = 'x'",
        "MERGE (m:Movie {title: 'x'})",
        "DROP CONSTRAINT movie_title",
    ],
)
def test_rejects_write_clauses(query: str) -> None:
    """Any write clause is rejected with UnsafeCypherError."""
    with pytest.raises(UnsafeCypherError):
        ensure_read_only(query)
```

### 3. Prompt builder test — `apps/agents/tests/test_prompts.py`

```python
"""Tests for prompt construction."""

from agents.prompts.system import GENERATE_SYSTEM_V1


def test_generate_prompt_embeds_context() -> None:
    """The generate prompt includes provided context text."""
    prompt = GENERATE_SYSTEM_V1.format(context="Forrest Gump (1994)")
    assert "Forrest Gump (1994)" in prompt
    assert "ONLY the retrieved context" in prompt
```

### 4. Backend test fixtures — `apps/backend/tests/conftest.py`

```python
"""Shared fixtures for backend route tests."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from api.auth import User, current_user
from api.deps import get_graph
from api.main import app


class _FakeGraph:
    """Minimal stand-in for the compiled agent graph."""

    async def astream_events(self, inputs, config, version):  # noqa: D102, ANN001
        yield {"event": "on_chat_model_stream", "data": {"chunk": type("C", (), {"content": "Hi"})()}}


@pytest.fixture
def anon_client() -> AsyncClient:
    """Client with the graph stubbed but auth NOT overridden (tests 401)."""
    app.dependency_overrides[get_graph] = lambda: _FakeGraph()
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client() -> AsyncClient:
    """Client with both the graph and auth stubbed (tests happy path)."""
    app.dependency_overrides[get_graph] = lambda: _FakeGraph()
    app.dependency_overrides[current_user] = lambda: User(id="u1", email="a@b.co")
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()
```

> If `app` import triggers `lifespan` (graph/DB build), guard the lifespan so it is skipped under tests (e.g. check an env var `APP_ENV=test`), OR build the app without running lifespan in tests. The dependency override for `get_graph` means the real graph is never needed.

### 5. Route contract tests — `apps/backend/tests/test_chat.py`

```python
"""Contract tests for the chat and health routes."""

import pytest


@pytest.mark.asyncio
async def test_health_ok(anon_client) -> None:
    """GET /health returns 200 and status ok."""
    async with anon_client as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_chat_requires_auth(anon_client) -> None:
    """POST /chat without a token returns 401/403."""
    async with anon_client as client:
        resp = await client.post("/chat", json={"message": "hi"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_chat_streams_for_authed_user(auth_client) -> None:
    """POST /chat with a stubbed user streams token frames."""
    async with auth_client as client:
        resp = await client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "Hi" in resp.text
```

### 6. Run

```powershell
uv run pytest -q
```

All tests pass with no network calls.

## Environment variables

Tests must not require real secrets. Set `APP_ENV=test` if used to skip lifespan side effects. Provide dummy values for any settings validated at import.

## Acceptance criteria

- [ ] `uv run pytest -q` passes with zero live network calls.
- [ ] Safety validator tests cover both allow and reject cases.
- [ ] `/chat` returns 401/403 without auth and streams with a stubbed user.
- [ ] `/health` contract test passes.
- [ ] Every test function has a docstring; `uv run ruff check .` passes.

## Do NOT

- Do NOT hit real OpenAI/Neo4j/Supabase in tests.
- Do NOT test only the happy path — include auth failure + unsafe Cypher.
- Do NOT leave `app.dependency_overrides` set across tests (clear in fixtures).

## Relevant rules & skills

- Rules: `testing`, `documentation`, `python-standards`.
- Skill: `verify-standards`.
