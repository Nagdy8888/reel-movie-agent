"""Contract tests for the full graph endpoint."""

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_graph_requires_auth(anon_client: TestClient) -> None:
    """GET /graph returns 401 without a valid token."""
    response = anon_client.get("/graph")
    assert response.status_code == 401


def test_graph_returns_full_graph(auth_client: TestClient) -> None:
    """GET /graph returns the full graph payload for authenticated users."""
    graph_payload = {
        "nodes": [
            {"id": "movie:the-matrix", "label": "The Matrix", "type": "Movie"},
            {"id": "person:keanu-reeves", "label": "Keanu Reeves", "type": "Person"},
        ],
        "links": [
            {
                "source": "person:keanu-reeves",
                "target": "movie:the-matrix",
                "label": "Acted In",
            }
        ],
    }
    with patch("api.routes.graph.full_graph", return_value=graph_payload) as mocked_full_graph:
        response = auth_client.get("/graph")

    assert response.status_code == 200
    assert response.json() == graph_payload
    mocked_full_graph.assert_called_once_with()
