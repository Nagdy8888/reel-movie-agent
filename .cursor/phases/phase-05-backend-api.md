# Phase 5 — FastAPI Backend (SSE Streaming + Health + Docker)

## Objective

Wrap the agent in a **FastAPI backend**:
- App factory + `lifespan` that builds the graph (with Postgres checkpointer + store) **eagerly** and stores it in `app.state`.
- `POST /chat` that **streams** the answer over **SSE** using `graph.astream_events(..., version="v3")`.
- `/health` (liveness) and `/ready` (checks Neo4j + checkpointer).
- Thin routes + DI + `response_model` on every route + structured logging.
- Dockerized backend service added to `docker-compose.yml`.

> **Implementation update:** the authenticated `GET /graph` route now returns
> the complete Movie/Person/Genre/Keyword graph using stable IDs. Large JSON
> responses are compressed by `GZipMiddleware`; the graph snapshot is cached
> in-process after the first successful Neo4j read.

**Auth, CORS, rate limiting, and security headers are added in Phase 6** — this phase keeps `/chat` open locally so you can test streaming first.

## Prerequisites

- Phase 4 complete: agent graph + memory factories work.
- Neo4j running; Supabase Postgres reachable via `SUPABASE_DB_URL`.

## Steps

### 1. Backend settings — `apps/backend/src/api/settings.py`

```python
"""Environment-backed configuration for the backend."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    """Settings for the FastAPI backend."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = Field(default="dev", description="dev | prod.")
    cors_allow_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated allowed CORS origins.",
    )
    supabase_url: str = Field(default="", description="Supabase project URL (auth).")
    supabase_jwt_aud: str = Field(default="authenticated", description="Expected JWT audience.")

    def origins(self) -> list[str]:
        """Return the CORS origin allowlist as a list."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


def get_settings() -> BackendSettings:
    """Return backend settings."""
    return BackendSettings()
```

### 2. Schemas — `apps/backend/src/api/schemas.py`

```python
"""Pydantic request/response models for the backend API."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A chat request from the client."""

    message: str = Field(description="The user's movie question.", min_length=1, max_length=2000)
    thread_id: str | None = Field(
        default=None, description="Conversation id for memory; server generates one if absent."
    )


class HealthResponse(BaseModel):
    """Health/readiness response."""

    status: str = Field(description="'ok' or 'degraded'.")
    detail: str = Field(default="", description="Optional detail message.")
```

### 3. Dependencies — `apps/backend/src/api/deps.py`

```python
"""FastAPI dependency providers."""

from typing import Annotated

from fastapi import Depends, Request

from api.settings import BackendSettings, get_settings

SettingsDep = Annotated[BackendSettings, Depends(get_settings)]


def get_graph(request: Request):
    """Return the compiled agent graph built during lifespan."""
    return request.app.state.graph


GraphDep = Annotated[object, Depends(get_graph)]
```

### 4. App factory + lifespan — `apps/backend/src/api/main.py`

```python
"""FastAPI application factory and lifespan for the Reel backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.graph import build_graph
from agents.memory import build_checkpointer, build_store
from api.routes import chat, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the graph with memory eagerly and stash it on app.state.

    Fails fast if Neo4j/Postgres/OpenAI config is missing.
    """
    checkpointer = build_checkpointer()
    store = build_store()
    app.state.graph = build_graph(checkpointer=checkpointer, store=store)
    app.state.checkpointer = checkpointer
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Reel API", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(chat.router)
    return app


app = create_app()
```

> Update `agents/graph.py::build_graph` to accept `checkpointer=None, store=None` and pass them to `builder.compile(checkpointer=..., store=...)`. Keep the module-level `graph = build_graph()` (no memory) for Studio.

### 5. Health routes — `apps/backend/src/api/routes/health.py`

```python
"""Liveness and readiness endpoints."""

from fastapi import APIRouter, Request, Response, status

from agents.clients import get_neo4j_driver
from api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Cheap liveness check; always 'ok' if the process is up."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request, response: Response) -> HealthResponse:
    """Readiness: verify Neo4j and the checkpointer are reachable."""
    try:
        get_neo4j_driver().verify_connectivity()
        _ = request.app.state.checkpointer
        return HealthResponse(status="ok")
    except Exception:  # noqa: BLE001 - readiness must never leak internals
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", detail="dependency unavailable")
```

Create `apps/backend/src/api/routes/__init__.py`:
```python
"""Backend HTTP route modules."""
```

### 6. Chat route with SSE streaming — `apps/backend/src/api/routes/chat.py`

```python
"""Chat endpoint that streams the agent's answer over SSE."""

import json
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from api.deps import GraphDep
from api.schemas import ChatRequest

router = APIRouter(tags=["chat"])


async def _event_stream(graph, body: ChatRequest):
    """Yield SSE frames for streamed answer tokens.

    Reads chat_model token events from astream_events v3 and forwards content.
    """
    thread_id = body.thread_id or str(uuid.uuid4())
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "run_name": "reel-chat",
        "tags": ["graphrag"],
        "metadata": {"thread_id": thread_id},
    }
    inputs = {"messages": [HumanMessage(content=body.message)]}
    yield f"event: meta\ndata: {json.dumps({'thread_id': thread_id})}\n\n"
    async for event in graph.astream_events(inputs, config, version="v3"):
        # REQUIRED filter: the `retrieve` node also makes LLM calls (Text2Cypher
        # + rerank), so restrict streamed tokens to the final `generate` node.
        if (
            event["event"] == "on_chat_model_stream"
            and event["metadata"].get("langgraph_node") == "generate"
        ):
            chunk = event["data"]["chunk"]
            text = getattr(chunk, "content", "")
            if text:
                yield f"data: {json.dumps({'token': text})}\n\n"
    yield "event: done\ndata: {}\n\n"


@router.post("/chat")
async def chat(body: ChatRequest, graph: GraphDep) -> StreamingResponse:
    """Stream an answer to the user's movie question via the agent graph."""
    return StreamingResponse(
        _event_stream(graph, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
```

> The final `generate` node's tokens stream via `on_chat_model_stream`. The `retrieve` node also invokes LLMs (Text2Cypher generation + reranking), so filtering by `event["metadata"].get("langgraph_node") == "generate"` is **required** — not optional — to guarantee only the grounded final answer reaches the client. (The retrieve-node utility LLM uses neo4j-graphrag's non-streaming client as defense in depth, but the node-name filter is the contract.)

### 7. Run locally

```powershell
uv run uvicorn api.main:app --reload --port 8000 --app-dir apps/backend/src
```

Test streaming:

```powershell
curl -N -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message":"What movies did Tom Hanks act in?"}'
```

You should see `data:` frames stream in, then `event: done`. Check `/health` and `/ready`.

### 8. Dockerize backend — `apps/backend/Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/agents ./apps/agents
COPY apps/backend ./apps/backend
RUN uv sync --frozen --package backend
# Non-root user (security requirement)
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "apps/backend/src", "--workers", "1"]
```

Add to `docker-compose.yml`:

```yaml
  backend:
    build:
      context: .
      dockerfile: apps/backend/Dockerfile
    env_file: [.env]
    environment:
      NEO4J_URI: bolt://neo4j:7687     # talk to the neo4j service, not localhost
    ports:
      - "8000:8000"
    depends_on:
      neo4j:
        condition: service_healthy
```

Run the stack:

```powershell
docker compose up -d neo4j backend
```

## Environment variables

Adds `APP_ENV`, `CORS_ALLOW_ORIGINS`, `SUPABASE_URL`, `SUPABASE_JWT_AUD`. Plus all prior vars. Inside Docker, `NEO4J_URI` must point at the `neo4j` service host.

## Acceptance criteria

- [ ] `uvicorn` starts; lifespan builds the graph with checkpointer + store (no error).
- [ ] `POST /chat` streams `data:` token frames and ends with `event: done`.
- [ ] Re-sending with the same `thread_id` continues the conversation (memory works).
- [ ] `/health` returns 200; `/ready` returns 200 when Neo4j+checkpointer are up, 503 otherwise.
- [ ] `docker compose up backend` runs the container as non-root with a working HEALTHCHECK.
- [ ] Every route has `response_model=` (except the SSE stream) and a docstring; `uv run ruff check .` passes.

## Do NOT

- Do NOT put graph orchestration logic in the route — the route only shapes the stream.
- Do NOT build the graph per request — it is built once in `lifespan`.
- Do NOT return `str(exc)` to clients (generic handler comes in Phase 6).
- Do NOT add auth-less deployment; local-only for now, secured next phase.

## Relevant rules & skills

- Rules: `fastapi-backend`, `python-standards`, `langgraph-agent`, `documentation`.
- Skill: `add-api-route` (follow its checklist), `verify-standards`.
