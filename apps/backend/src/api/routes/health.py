"""Liveness and readiness endpoints."""

import psycopg
from fastapi import APIRouter, Request, Response, status

from agents.lightrag_service import lightrag_ready
from agents.settings import get_settings
from api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Cheap liveness check; always 'ok' if the process is up."""
    return HealthResponse(status="ok")


def _supabase_ready() -> bool:
    """Return True when the Supabase Postgres accepts a trivial query."""
    settings = get_settings()
    try:
        with psycopg.connect(settings.supabase_db_url, connect_timeout=5) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request, response: Response) -> HealthResponse:
    """Readiness: verify LightRAG Postgres, Supabase, and the checkpointer."""
    try:
        if not await lightrag_ready():
            raise RuntimeError("lightrag postgres unavailable")
        if not _supabase_ready():
            raise RuntimeError("supabase unavailable")
        _ = request.app.state.checkpointer
        return HealthResponse(status="ok")
    except Exception:  # noqa: BLE001 - readiness must never leak internals
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", detail="dependency unavailable")
