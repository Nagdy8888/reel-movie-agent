"""Application-level error handling contract tests."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import create_app


def test_unhandled_error_returns_generic_body_with_request_id() -> None:
    """Unexpected route failures never expose exception details to clients."""
    with (
        patch("api.main.build_checkpointer", return_value=MagicMock()),
        patch("api.main.build_store", return_value=MagicMock()),
        patch("api.main.build_graph", return_value=MagicMock()),
        patch("api.main.open_pool", return_value=MagicMock()),
    ):
        app = create_app()

        @app.get("/test-unhandled")
        async def _raise_unhandled() -> None:
            """Raise a test-only unexpected exception."""
            raise RuntimeError("private database detail")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/test-unhandled",
                headers={"X-Request-ID": "test-request-id"},
            )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "request_id": "test-request-id",
    }
    assert "private database detail" not in response.text
