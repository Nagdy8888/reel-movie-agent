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
            {"id": "movie:603", "label": "The Matrix", "type": "Movie"},
            {"id": "person:6384", "label": "Keanu Reeves", "type": "Person"},
            {
                "id": "genre:science%20fiction",
                "label": "Science Fiction",
                "type": "Genre",
            },
        ],
        "links": [
            {
                "source": "person:6384",
                "target": "movie:603",
                "label": "Acted In",
            }
        ],
    }
    with patch("api.routes.graph.full_graph", return_value=graph_payload) as mocked_full_graph:
        response = auth_client.get("/graph")

    assert response.status_code == 200
    assert response.json() == graph_payload
    mocked_full_graph.assert_called_once_with()


def test_graph_response_is_compressed_when_large(auth_client: TestClient) -> None:
    """Large full-graph JSON responses should use transport compression."""
    graph_payload = {
        "nodes": [
            {"id": f"movie:{index}", "label": f"Movie {index}", "type": "Movie"}
            for index in range(100)
        ],
        "links": [],
    }
    with patch("api.routes.graph.full_graph", return_value=graph_payload):
        response = auth_client.get("/graph", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert len(response.json()["nodes"]) == 100
