# Phase 6 — Auth, Security Hardening & Chat Persistence

## Objective

Lock down the backend to production standards **and** add per-user, persistent chat history:

- **Supabase JWT auth** (verify Bearer token against the project JWKS, RS256, `aud=authenticated`) as a dependency on protected routes.
- **CORS** with an explicit origin allowlist (never `*` with credentials).
- **Rate limiting** on `/chat` (per-IP) via `slowapi`.
- **Security headers** middleware + **request-ID** + **structured JSON logging**.
- **Generic error handler** returning `{"detail": "Internal server error", "request_id": ...}` — never `str(exc)`.
- **Startup env validation** (refuse to boot on missing/placeholder secrets in prod).
- **Chat persistence**: new `public.conversations` + `public.messages` tables in Supabase, written by the backend on every turn and exposed through `GET /chats`, `GET /chats/{id}`, and `DELETE /chats/{id}`.

> **Memory is already in Supabase.** The LangGraph checkpointer/store from Phase 5 already persist conversation state to Supabase Postgres (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `store`). This phase adds a **user-facing** chat layer on top: `conversations.thread_id` is the same `thread_id` passed to the graph, so a chat row links to its checkpoint state. The `messages` table is an explicit per-turn log for listing/pagination.

## Prerequisites

- Phase 5 complete: backend streams `/chat`.
- The **`Reel` Supabase project** (`project_id: "bkhmqtcxoxtrydumgwfd"`) with **asymmetric (RS256) JWT signing keys enabled**.

**Get config via the Supabase MCP plugin (not the dashboard).** See `.cursor/rules/supabase-mcp.mdc`.

- `get_project_url` (project_id `bkhmqtcxoxtrydumgwfd`) → `SUPABASE_URL=https://bkhmqtcxoxtrydumgwfd.supabase.co`. Put it in `.env`.
- `get_publishable_keys` (project_id `bkhmqtcxoxtrydumgwfd`) → the publishable/anon key for the frontend (Phase 8). Write it only into env files, never committed.
- The JWKS endpoint is `${SUPABASE_URL}/auth/v1/.well-known/jwks.json` (used below). If verification fails because the project still uses a legacy HS256 secret, enable asymmetric JWT signing keys for the project, then re-run; use `search_docs` for the current steps.

## Data flow

```mermaid
flowchart LR
  client["Client"] -->|"POST /chat + Bearer JWT"| chatRoute["/chat route"]
  chatRoute -->|"upsert + user msg"| convTbl["public.conversations"]
  chatRoute -->|"stream tokens"| graph["LangGraph graph"]
  graph -->|"checkpoint state"| ckpt["checkpoints (Supabase)"]
  chatRoute -->|"assistant msg after stream"| msgTbl["public.messages"]
  client -->|"GET /chats, GET /chats/id"| chatsRoute["/chats routes"]
  chatsRoute --> convTbl
  chatsRoute --> msgTbl
```

## Steps

### 1. Supabase schema — chat tables (via MCP `apply_migration`)

Apply a migration named `create_chat_tables` to project `bkhmqtcxoxtrydumgwfd`. Never hand-write schema through `execute_sql` — use `apply_migration` so it lands in the migration history.

```sql
create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  thread_id text not null unique,
  title text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists conversations_user_updated_idx
  on public.conversations (user_id, updated_at desc);
create index if not exists messages_conversation_created_idx
  on public.messages (conversation_id, created_at);

alter table public.conversations enable row level security;
alter table public.messages enable row level security;

create policy "conversations are owner-only"
  on public.conversations for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "messages are owner-only"
  on public.messages for all
  using (exists (
    select 1 from public.conversations c
    where c.id = messages.conversation_id and c.user_id = auth.uid()
  ))
  with check (exists (
    select 1 from public.conversations c
    where c.id = messages.conversation_id and c.user_id = auth.uid()
  ));
```

After applying, run `get_advisors` (type `security`) and resolve findings. RLS is **defense-in-depth**: the backend connects with the direct Postgres role (`SUPABASE_DB_URL`) which bypasses RLS, so backend reads/writes always work; the policies protect any future PostgREST/anon access.

### 2. Backend deps + settings

`apps/backend/pyproject.toml` — add Postgres deps (`pyjwt[crypto]`, `slowapi`, `python-json-logger` are already present):

```toml
  "psycopg[binary]>=3.2",
  "psycopg-pool>=3.2",
```

`apps/backend/src/api/settings.py` — add the DB URL field:

```python
    supabase_db_url: str = Field(
        default="", description="Postgres URL for chat persistence (Supabase)."
    )
```

### 3. Chat DB pool — `apps/backend/src/api/db.py`

Sync pool + `run_in_threadpool` (not async) for cross-platform parity with the Phase 5 streaming fix — async psycopg pools fail on the Windows Proactor loop.

```python
"""Sync Postgres connection pool for backend chat persistence."""

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from api.settings import get_settings


def open_pool() -> ConnectionPool[Connection[DictRow]]:
    """Open and return a Postgres pool for the chat tables.

    Opened eagerly in the app lifespan and closed on shutdown.
    """
    settings = get_settings()
    return ConnectionPool(
        conninfo=settings.supabase_db_url,
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
```

### 4. Persistence service — `apps/backend/src/api/services/chats.py`

Thin, user-scoped repository. Every read/write filters by `user_id`; routes call these via `run_in_threadpool`.

```python
"""Persistence for user conversations and messages (Supabase Postgres)."""

from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg_pool import ConnectionPool


class ChatStore:
    """CRUD for conversations and messages, always scoped to a user."""

    def __init__(self, pool: ConnectionPool[Connection[DictRow]]) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    def upsert_conversation(
        self, user_id: str, thread_id: str, title: str
    ) -> dict[str, Any] | None:
        """Insert or touch a conversation.

        Returns the row, or None if the thread already exists under a different
        user (caller should treat that as 403).
        """
        with self._pool.connection() as conn:
            return conn.execute(
                """
                INSERT INTO conversations (user_id, thread_id, title)
                VALUES (%s, %s, %s)
                ON CONFLICT (thread_id) DO UPDATE SET updated_at = now()
                WHERE conversations.user_id = EXCLUDED.user_id
                RETURNING id, user_id, thread_id, title, created_at, updated_at
                """,
                (user_id, thread_id, title),
            ).fetchone()

    def add_message(self, conversation_id: str, role: str, content: str) -> None:
        """Append a message row to a conversation."""
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conversation_id, role, content),
            )

    def touch(self, conversation_id: str) -> None:
        """Bump a conversation's updated_at."""
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = now() WHERE id = %s",
                (conversation_id,),
            )

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Return the user's conversations, newest first."""
        with self._pool.connection() as conn:
            return conn.execute(
                """
                SELECT id, thread_id, title, created_at, updated_at
                FROM conversations WHERE user_id = %s ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()

    def get_for_user(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        """Return one conversation with ordered messages, or None if not owned."""
        with self._pool.connection() as conn:
            conv = conn.execute(
                """
                SELECT id, thread_id, title, created_at, updated_at
                FROM conversations WHERE id = %s AND user_id = %s
                """,
                (conversation_id, user_id),
            ).fetchone()
            if conv is None:
                return None
            conv["messages"] = conn.execute(
                """
                SELECT role, content, created_at FROM messages
                WHERE conversation_id = %s ORDER BY created_at
                """,
                (conversation_id,),
            ).fetchall()
        return conv

    def delete_for_user(self, user_id: str, conversation_id: str) -> bool:
        """Delete a conversation (messages cascade). Returns True if a row was removed."""
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
        return cur.rowcount > 0
```

Add an empty package marker `apps/backend/src/api/services/__init__.py`:

```python
"""Backend service layer (business logic, persistence)."""
```

### 5. JWT auth dependency — `apps/backend/src/api/auth.py`

```python
"""Supabase JWT verification dependency (JWKS / RS256)."""

from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from api.settings import BackendSettings, get_settings

_bearer = HTTPBearer(auto_error=True)


class User(BaseModel):
    """Authenticated user extracted from a verified JWT."""

    id: str
    email: str | None = None


@lru_cache(maxsize=1)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Return a cached JWKS client for the given URL."""
    return jwt.PyJWKClient(jwks_url)


def current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    settings: BackendSettings = Depends(get_settings),
) -> User:
    """Verify the Bearer JWT against Supabase JWKS and return the user.

    Raises:
        HTTPException: 401 if the token is missing/invalid/expired.
    """
    token = creds.credentials
    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.supabase_jwt_aud,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    return User(id=claims["sub"], email=claims.get("email"))
```

### 6. Dependencies — update `apps/backend/src/api/deps.py`

```python
"""FastAPI dependency providers."""

from typing import Annotated

from fastapi import Depends, Request

from api.auth import User, current_user
from api.services.chats import ChatStore
from api.settings import BackendSettings, get_settings

SettingsDep = Annotated[BackendSettings, Depends(get_settings)]
UserDep = Annotated[User, Depends(current_user)]


def get_graph(request: Request):
    """Return the compiled agent graph built during lifespan."""
    return request.app.state.graph


def get_chat_store(request: Request) -> ChatStore:
    """Return a chat store bound to the app's Postgres pool."""
    return ChatStore(request.app.state.db_pool)


GraphDep = Annotated[object, Depends(get_graph)]
ChatStoreDep = Annotated[ChatStore, Depends(get_chat_store)]
```

### 7. Shared rate limiter — `apps/backend/src/api/limiter.py`

A separate module so both `main.py` and the chat route import the same `limiter` without a circular import.

```python
"""Shared slowapi limiter."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

### 8. Security headers + request-ID + logging — `apps/backend/src/api/middleware.py`

```python
"""Cross-cutting middleware: request-id, security headers, structured logging."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("reel.access")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Cache-Control": "no-store",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, set security headers, and log each request."""

    async def dispatch(self, request: Request, call_next):
        """Process one request with a bound request id and security headers."""
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers.update(_SECURITY_HEADERS)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return response
```

Never log tokens, message bodies, or PII.

### 9. Schemas — update `apps/backend/src/api/schemas.py`

```python
from datetime import datetime
from uuid import UUID


class MessageOut(BaseModel):
    """A single stored chat message."""

    role: str = Field(description="'user' or 'assistant'.")
    content: str = Field(description="Message text.")
    created_at: datetime = Field(description="When the message was stored.")


class ConversationSummary(BaseModel):
    """A conversation without its messages (for list views)."""

    id: UUID = Field(description="Conversation id.")
    thread_id: str = Field(description="LangGraph thread id backing this chat.")
    title: str | None = Field(default=None, description="Short title derived from the first message.")
    created_at: datetime = Field(description="Creation time.")
    updated_at: datetime = Field(description="Last activity time.")


class ConversationDetail(ConversationSummary):
    """A conversation with its ordered messages."""

    messages: list[MessageOut] = Field(description="Messages in chronological order.")
```

### 10. Chat route — protect + persist — `apps/backend/src/api/routes/chat.py`

Require the user, upsert the conversation, store the user message before streaming, accumulate the assistant answer, and store it after `event: done`. Attach `user_id` to LangSmith metadata and return `conversation_id` in the `meta` frame.

```python
"""Chat endpoint that streams the agent's answer over SSE and persists history."""

import json
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from api.deps import ChatStoreDep, GraphDep, UserDep
from api.limiter import limiter
from api.schemas import ChatRequest
from api.services.chats import ChatStore

router = APIRouter(tags=["chat"])


def _token_from_v3_event(raw: dict) -> str:
    """Extract a streamed text token from a LangGraph v3 ``messages`` event."""
    if raw.get("method") != "messages":
        return ""
    data = raw.get("params", {}).get("data")
    if not isinstance(data, tuple) or len(data) != 2:
        return ""
    payload, metadata = data
    if metadata.get("langgraph_node") != "generate":
        return ""
    if payload.get("event") != "content-block-delta":
        return ""
    delta = payload.get("delta", {})
    if delta.get("type") != "text-delta":
        return ""
    return str(delta.get("text", ""))


async def _event_stream(
    graph, body: ChatRequest, user_id: str, thread_id: str, conversation_id: str, store: ChatStore
):
    """Yield SSE frames for streamed answer tokens and persist the assistant reply.

    Sync iteration runs in a thread pool so the event loop stays responsive and
    the sync Postgres checkpointer/store work on all platforms (Windows included).
    """
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "run_name": "reel-chat",
        "tags": ["graphrag"],
        "metadata": {"thread_id": thread_id, "user_id": user_id},
    }
    inputs = {"messages": [HumanMessage(content=body.message)]}
    yield f"event: meta\ndata: {json.dumps({'thread_id': thread_id, 'conversation_id': conversation_id})}\n\n"
    parts: list[str] = []
    stream = graph.stream_events(inputs, config, version="v3")
    async for raw in iterate_in_threadpool(stream):
        text = _token_from_v3_event(raw)
        if text:
            parts.append(text)
            yield f"data: {json.dumps({'token': text})}\n\n"
    answer = "".join(parts)
    if answer:
        await run_in_threadpool(store.add_message, conversation_id, "assistant", answer)
        await run_in_threadpool(store.touch, conversation_id)
    yield "event: done\ndata: {}\n\n"


@router.post("/chat")
@limiter.limit("20/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    graph: GraphDep,
    user: UserDep,
    store: ChatStoreDep,
) -> StreamingResponse:
    """Stream an answer to the authenticated user's movie question and persist it."""
    thread_id = body.thread_id or str(uuid.uuid4())
    conversation = await run_in_threadpool(
        store.upsert_conversation, user.id, thread_id, body.message[:60]
    )
    if conversation is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Thread not owned by user")
    await run_in_threadpool(store.add_message, conversation["id"], "user", body.message)
    return StreamingResponse(
        _event_stream(graph, body, user.id, thread_id, str(conversation["id"]), store),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
```

> `slowapi` requires the `request: Request` parameter on the limited handler. If the client disconnects mid-stream, the user message is already saved; the assistant row is simply skipped and the chat stays resumable from its checkpoint.

### 11. Chats routes — `apps/backend/src/api/routes/chats.py`

```python
"""User chat history endpoints (list, fetch, delete)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from starlette.concurrency import run_in_threadpool

from api.auth import current_user
from api.deps import ChatStoreDep, UserDep
from api.schemas import ConversationDetail, ConversationSummary

router = APIRouter(prefix="/chats", tags=["chats"], dependencies=[Depends(current_user)])


@router.get("", response_model=list[ConversationSummary])
async def list_chats(user: UserDep, store: ChatStoreDep) -> list[ConversationSummary]:
    """List the authenticated user's conversations, newest first."""
    rows = await run_in_threadpool(store.list_for_user, user.id)
    return [ConversationSummary(**row) for row in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_chat(
    conversation_id: UUID, user: UserDep, store: ChatStoreDep
) -> ConversationDetail:
    """Return one conversation with its messages; 404 if not owned."""
    row = await run_in_threadpool(store.get_for_user, user.id, str(conversation_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return ConversationDetail(**row)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    conversation_id: UUID, user: UserDep, store: ChatStoreDep
) -> Response:
    """Delete a conversation and its messages; 404 if not owned."""
    ok = await run_in_threadpool(store.delete_for_user, user.id, str(conversation_id))
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

`DELETE` is the one route without a `response_model` (it returns `204 No Content`).

### 12. App factory — CORS, validation, logging, error handler, rate limit, lifespan — `apps/backend/src/api/main.py`

```python
"""FastAPI application factory and lifespan for the Reel backend."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from agents.graph import build_graph
from agents.memory import build_checkpointer, build_store
from api.db import open_pool
from api.limiter import limiter
from api.middleware import RequestContextMiddleware
from api.routes import chat, chats, health
from api.settings import BackendSettings, get_settings

logger = logging.getLogger("reel")


def _configure_logging() -> None:
    """Configure structured JSON logging for the process."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def _validate_env(settings: BackendSettings) -> None:
    """Fail fast if required secrets are missing or placeholders in prod."""
    if settings.app_env == "prod":
        missing = [
            k
            for k, v in {
                "SUPABASE_URL": settings.supabase_url,
                "SUPABASE_DB_URL": settings.supabase_db_url,
                "CORS_ALLOW_ORIGINS": settings.cors_allow_origins,
            }.items()
            if not v or "change-me" in v or v == "*"
        ]
        if missing:
            raise RuntimeError(f"Missing/placeholder config in prod: {missing}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build graph memory + chat DB pool eagerly; close the pool on shutdown.

    Fails fast if Neo4j/Postgres/OpenAI config is missing.
    """
    checkpointer = build_checkpointer()
    store = build_store()
    app.state.graph = build_graph(checkpointer=checkpointer, store=store)
    app.state.checkpointer = checkpointer
    app.state.db_pool = open_pool()
    yield
    app.state.db_pool.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    _configure_logging()
    settings = get_settings()
    _validate_env(settings)

    app = FastAPI(title="Reel API", version="0.1.0", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins(),  # explicit list, never ["*"] with credentials
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Return a generic 500 body; log the full trace with the request id."""
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception("unhandled", extra={"request_id": request_id})
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(chats.router)
    return app


app = create_app()
```

Health routes stay public. Depending on the installed `python-json-logger`, the import may be `from pythonjsonlogger import jsonlogger` (v2) or `from pythonjsonlogger.json import JsonFormatter` (v3) — adjust if the import fails.

### 13. Tests — `apps/backend/tests/`

Mock the graph, the DB (`ChatStore`), and `open_pool`; override `current_user` for authed cases (no live network, per the testing rule).

`conftest.py`:

```python
"""Shared fixtures for backend route contract tests."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import User, current_user
from api.deps import get_chat_store
from api.main import create_app


@pytest.fixture
def mock_graph() -> MagicMock:
    """Return a mock graph whose stream_events yields one generate-node token."""
    graph = MagicMock()

    def _stream_events(_inputs, _config, *, version):
        del version
        yield {
            "type": "event",
            "method": "messages",
            "params": {
                "data": (
                    {"event": "content-block-delta", "index": 0,
                     "delta": {"type": "text-delta", "text": "Hello"}},
                    {"langgraph_node": "generate"},
                )
            },
            "seq": 1,
        }

    graph.stream_events = _stream_events
    return graph


@pytest.fixture
def mock_store() -> MagicMock:
    """Return a ChatStore stub with sensible defaults."""
    store = MagicMock()
    store.upsert_conversation.return_value = {"id": "11111111-1111-1111-1111-111111111111"}
    store.list_for_user.return_value = []
    store.get_for_user.return_value = None
    store.delete_for_user.return_value = True
    return store


def _make_app(mock_graph: MagicMock, mock_store: MagicMock):
    """Build an app with lifespan deps + chat store stubbed out."""
    with (
        patch("api.main.build_checkpointer", return_value=MagicMock()),
        patch("api.main.build_store", return_value=MagicMock()),
        patch("api.main.build_graph", return_value=mock_graph),
        patch("api.main.open_pool", return_value=MagicMock()),
    ):
        app = create_app()
    app.dependency_overrides[get_chat_store] = lambda: mock_store
    return app


@pytest.fixture
def anon_client(mock_graph, mock_store) -> TestClient:
    """Client without auth overridden (exercises 401)."""
    app = _make_app(mock_graph, mock_store)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_client(mock_graph, mock_store) -> TestClient:
    """Client with auth overridden to a fixed user (exercises happy paths)."""
    app = _make_app(mock_graph, mock_store)
    app.dependency_overrides[current_user] = lambda: User(id="user-1", email="a@b.co")
    with TestClient(app) as client:
        yield client
```

Cover: `POST /chat` → 401 without token, streams + persists (assert `mock_store.add_message` called for user and assistant) with the override, 403 when `upsert_conversation` returns `None`; `GET /chats`, `GET /chats/{id}` (200 + 404 when not owned), `DELETE /chats/{id}` (204 + 404). Health stays public.

### 14. Run & verify

```powershell
uv run uvicorn api.main:app --reload --port 8000 --app-dir apps/backend/src
```

- `POST /chat` without a token → 401.
- With a valid Supabase JWT (`Authorization: Bearer <token>`) → streams; the `meta` frame carries `thread_id` + `conversation_id`.
- Verify rows landed: `execute_sql` (project `bkhmqtcxoxtrydumgwfd`) `select role, left(content, 40) from messages order by created_at desc limit 4;`.
- `GET /chats` (with token) lists the conversation; `GET /chats/{id}` returns its messages; `DELETE /chats/{id}` → 204 and cascades messages.
- Every response carries security headers + `X-Request-ID`.
- Forcing an error returns the generic body with `request_id` (no stack trace leaked).
- Exceeding 20 requests/min on `/chat` → 429.
- `uv run ruff check .` and `uv run pytest apps/backend/tests` pass; `get_advisors` (security) clean.

## Environment variables

`SUPABASE_URL`, `SUPABASE_JWT_AUD`, `SUPABASE_DB_URL`, `CORS_ALLOW_ORIGINS`, `APP_ENV`. Inside Docker, `SUPABASE_DB_URL` points at Supabase (not the local `neo4j` service).

## Acceptance criteria

- [ ] `public.conversations` + `public.messages` exist with FKs, indexes, and owner-only RLS policies; `get_advisors` (security) is clean.
- [ ] Protected routes reject missing/invalid/expired tokens with 401 (via JWKS verification); health stays public.
- [ ] `POST /chat` persists the user message and the assistant reply, tied to the user, and returns `conversation_id` in the `meta` frame.
- [ ] Re-using another user's `thread_id` → 403; using your own continues the conversation (memory works).
- [ ] `GET /chats` lists only the caller's conversations; `GET /chats/{id}` returns messages (404 if not owned); `DELETE /chats/{id}` → 204 and cascades.
- [ ] CORS uses the explicit allowlist from settings; no `*`.
- [ ] Every response carries security headers + `X-Request-ID`.
- [ ] Unhandled errors return the generic body + `request_id`; full trace only in server logs.
- [ ] `/chat` is rate-limited (429 after the cap).
- [ ] In `prod`, boot fails on missing/placeholder `SUPABASE_URL`/`SUPABASE_DB_URL`/`CORS_ALLOW_ORIGINS`.
- [ ] No secrets/PII in logs; `response_model=` on every route (except the SSE stream and the 204 delete); `uv run ruff check .` passes; all functions documented.

## Do NOT

- Do NOT compare secrets with `==` — use `hmac.compare_digest` where you compare secrets.
- Do NOT set `allow_origins=["*"]` with `allow_credentials=True`.
- Do NOT log the JWT, the user message, or any PII.
- Do NOT return exception details to clients.
- Do NOT build SQL by string interpolation — always use parameterized queries.
- Do NOT read/write chat rows without filtering by the authenticated `user_id`.
- Do NOT open the Postgres pool per request — open once in `lifespan`.

## Relevant rules & skills

- Rules: `security`, `fastapi-backend`, `python-standards`, `supabase-mcp`, `documentation`.
- Skill: `add-api-route` (follow its checklist), `verify-standards`.
