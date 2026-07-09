"""Contract tests for health and readiness endpoints."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """Liveness endpoint always returns status ok when the process is up."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "detail": ""}


def test_ready_returns_ok_when_dependencies_up(client: TestClient) -> None:
    """Readiness returns 200 when Neo4j and the checkpointer are reachable."""
    mock_driver = MagicMock()
    with patch("api.routes.health.get_neo4j_driver", return_value=mock_driver):
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "detail": ""}
    mock_driver.verify_connectivity.assert_called_once()


def test_ready_returns_503_when_neo4j_unavailable(client: TestClient) -> None:
    """Readiness returns 503 without leaking exception details."""
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.side_effect = OSError("connection refused")
    with patch("api.routes.health.get_neo4j_driver", return_value=mock_driver):
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "detail": "dependency unavailable"}
