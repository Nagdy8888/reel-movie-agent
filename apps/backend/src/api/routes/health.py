"""Liveness and readiness endpoints."""

from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from agents.lightrag_service import lightrag_ready
from api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Cheap liveness check; always 'ok' if the process is up."""
    return HealthResponse(status="ok")


def _verify_postgres_dependencies(request: Request) -> None:
    """Probe the app's Supabase pool and LangGraph checkpointer."""
    request.app.state.db_pool.check()
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": "__readiness__",
            "checkpoint_ns": "",
        }
    }
    request.app.state.checkpointer.get_tuple(config)


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request, response: Response) -> HealthResponse:
    """Readiness: verify LightRAG Postgres, Supabase, and the checkpointer."""
    try:
        if not await lightrag_ready():
            raise RuntimeError("lightrag postgres unavailable")
        await run_in_threadpool(_verify_postgres_dependencies, request)
        return HealthResponse(status="ok")
    except Exception:  # noqa: BLE001 - readiness must never leak internals
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", detail="dependency unavailable")
