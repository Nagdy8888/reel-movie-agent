# Phase 6 — Auth & Security Hardening

## Objective

Lock down the backend to production standards:
- **Supabase JWT auth** (verify Bearer token against the project JWKS, RS256, `aud=authenticated`) as a dependency on protected routes.
- **CORS** with an explicit origin allowlist (never `*` with credentials).
- **Rate limiting** on `/chat` (per-IP) via `slowapi`.
- **Security headers** middleware + **request-ID** + **structured JSON logging**.
- **Generic error handler** returning `{"detail": "Internal server error", "request_id": ...}` — never `str(exc)`.
- **Startup env validation** (refuse to boot on missing/placeholder secrets in prod).

## Prerequisites

- Phase 5 complete: backend streams `/chat`.
- The **`Reel` Supabase project** (`project_id: "bkhmqtcxoxtrydumgwfd"`) with **asymmetric (RS256) JWT signing keys enabled**.

**Get config via the Supabase MCP plugin (not the dashboard).** See `.cursor/rules/supabase-mcp.mdc`.

- `get_project_url` (project_id `bkhmqtcxoxtrydumgwfd`) → `SUPABASE_URL=https://bkhmqtcxoxtrydumgwfd.supabase.co`. Put it in `.env`.
- `get_publishable_keys` (project_id `bkhmqtcxoxtrydumgwfd`) → the publishable/anon key for the frontend (Phase 8). Write it only into env files, never committed.
- The JWKS endpoint is `${SUPABASE_URL}/auth/v1/.well-known/jwks.json` (used below). If verification fails because the project still uses a legacy HS256 secret, enable asymmetric JWT signing keys for the project, then re-run; use `search_docs` for the current steps.

## Steps

### 1. JWT auth dependency — `apps/backend/src/api/auth.py`

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

Add the user dependency to `deps.py`:
```python
from api.auth import User, current_user

UserDep = Annotated[User, Depends(current_user)]
```

Protect `/chat` — update its handler signature to require the user and attach `user.id` to LangSmith metadata:
```python
@router.post("/chat")
async def chat(body: ChatRequest, graph: GraphDep, user: UserDep) -> StreamingResponse:
    """Stream an answer to the authenticated user's movie question."""
    ...
    # in config metadata: {"thread_id": thread_id, "user_id": user.id}
```

Health routes stay public.

### 2. CORS + startup validation — update `main.py`

```python
from fastapi.middleware.cors import CORSMiddleware


def _validate_env(settings: BackendSettings) -> None:
    """Fail fast if required secrets are missing or placeholders in prod."""
    if settings.app_env == "prod":
        missing = [k for k, v in {
            "SUPABASE_URL": settings.supabase_url,
            "CORS_ALLOW_ORIGINS": settings.cors_allow_origins,
        }.items() if not v or "change-me" in v or v == "*"]
        if missing:
            raise RuntimeError(f"Missing/placeholder config in prod: {missing}")
```

In `create_app()`:
```python
    settings = get_settings()
    _validate_env(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins(),   # explicit list, never ["*"] with credentials
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
```

### 3. Security headers + request-ID + logging — `apps/backend/src/api/middleware.py`

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

Configure JSON logging in `main.py` startup (use `python-json-logger`), and `app.add_middleware(RequestContextMiddleware)`. Never log tokens, message bodies, or PII.

### 4. Generic error handler — in `main.py`

```python
from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a generic 500 body; log the full trace with the request id."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("unhandled", extra={"request_id": request_id})
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )
```

### 5. Rate limiting on `/chat` — `slowapi`

In `main.py`:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

On the chat route:
```python
from slowapi.util import get_remote_address  # noqa: F401

@router.post("/chat")
@limiter.limit("20/minute")
async def chat(request: Request, body: ChatRequest, graph: GraphDep, user: UserDep) -> StreamingResponse:
    ...
```
(`slowapi` requires the `request: Request` parameter on the limited handler.)

> Trust proxy headers only behind Caddy (Phase 9). Do NOT trust `X-Forwarded-For` unless the proxy is known — configure `slowapi`/uvicorn `--forwarded-allow-ips` accordingly at deploy time.

### 6. Verify

```powershell
uv run uvicorn api.main:app --reload --port 8000 --app-dir apps/backend/src
```

- `POST /chat` without a token → 401.
- With a valid Supabase JWT (`Authorization: Bearer <token>`) → streams normally.
- Response includes `X-Request-ID` and security headers.
- Forcing an error returns the generic body with `request_id` (no stack trace leaked).
- Exceeding 20 requests/min on `/chat` → 429.

## Environment variables

`SUPABASE_URL`, `SUPABASE_JWT_AUD`, `CORS_ALLOW_ORIGINS`, `APP_ENV`.

## Acceptance criteria

- [ ] Protected routes reject missing/invalid/expired tokens with 401 (via JWKS verification).
- [ ] CORS uses the explicit allowlist from settings; no `*`.
- [ ] Every response carries security headers + `X-Request-ID`.
- [ ] Unhandled errors return the generic body + `request_id`; full trace only in server logs.
- [ ] `/chat` is rate-limited (429 after the cap).
- [ ] In `prod`, boot fails on missing/placeholder `SUPABASE_URL`/`CORS_ALLOW_ORIGINS`.
- [ ] No secrets/PII in logs; `uv run ruff check .` passes; all functions documented.

## Do NOT

- Do NOT compare secrets with `==` — use `hmac.compare_digest` where you compare secrets.
- Do NOT set `allow_origins=["*"]` with `allow_credentials=True`.
- Do NOT log the JWT, the user message, or any PII.
- Do NOT return exception details to clients.

## Relevant rules & skills

- Rules: `security`, `fastapi-backend`, `python-standards`, `documentation`.
- Skill: `verify-standards`.
