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
        allow_origins=settings.origins(),
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
