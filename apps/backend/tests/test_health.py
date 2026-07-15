"""Contract tests for health and readiness endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """Liveness endpoint always returns status ok when the process is up."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "detail": ""}


def test_ready_returns_ok_when_dependencies_up(client: TestClient) -> None:
    """Readiness returns 200 when LightRAG Postgres, Supabase, and checkpointer are up."""
    with (
        patch("api.routes.health.lightrag_ready", new=AsyncMock(return_value=True)),
        patch("api.routes.health._verify_postgres_dependencies"),
    ):
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "detail": ""}


def test_ready_returns_503_when_lightrag_unavailable(client: TestClient) -> None:
    """Readiness returns 503 without leaking exception details."""
    with (
        patch("api.routes.health.lightrag_ready", new=AsyncMock(return_value=False)),
        patch("api.routes.health._verify_postgres_dependencies"),
    ):
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "detail": "dependency unavailable"}


def test_ready_returns_503_when_supabase_unavailable(client: TestClient) -> None:
    """Readiness returns 503 when the Supabase projection/checkpointer DB is down."""
    with (
        patch("api.routes.health.lightrag_ready", new=AsyncMock(return_value=True)),
        patch(
            "api.routes.health._verify_postgres_dependencies",
            side_effect=OSError("connection refused"),
        ),
    ):
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "detail": "dependency unavailable"}
