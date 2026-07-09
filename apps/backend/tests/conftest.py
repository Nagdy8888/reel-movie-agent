"""Shared fixtures for backend route contract tests."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def mock_graph() -> MagicMock:
    """Return a mock graph whose stream_events yields one generate-node token."""
    graph = MagicMock()

    def _stream_events(
        _inputs: dict,
        _config: dict,
        *,
        version: str,
    ):
        del version
        yield {
            "type": "event",
            "method": "messages",
            "params": {
                "data": (
                    {
                        "event": "content-block-delta",
                        "index": 0,
                        "delta": {"type": "text-delta", "text": "Hello"},
                    },
                    {"langgraph_node": "generate"},
                ),
            },
            "seq": 1,
        }

    graph.stream_events = _stream_events
    return graph


@pytest.fixture
def client(mock_graph: MagicMock) -> TestClient:
    """Return a TestClient with lifespan dependencies mocked."""
    mock_checkpointer = MagicMock()
    with (
        patch("api.main.build_checkpointer", return_value=mock_checkpointer),
        patch("api.main.build_store", return_value=MagicMock()),
        patch("api.main.build_graph", return_value=mock_graph),
    ):
        with TestClient(create_app()) as test_client:
            yield test_client
