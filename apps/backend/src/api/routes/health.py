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
