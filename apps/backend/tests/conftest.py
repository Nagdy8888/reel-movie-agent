"""Shared fixtures for backend route contract tests."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import User, current_user
from api.deps import get_chat_store
from api.main import create_app


@pytest.fixture
def mock_graph() -> MagicMock:
    """Return a mock graph whose stream_events yields one generate-node token."""
    graph = MagicMock()

    def _stream_events(_inputs, _config, *, version):
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
                )
            },
            "seq": 1,
        }

    graph.stream_events = _stream_events
    return graph


@pytest.fixture
def mock_store() -> MagicMock:
    """Return a ChatStore stub with sensible defaults."""
    store = MagicMock()
    store.upsert_conversation.return_value = {"id": "11111111-1111-1111-1111-111111111111"}
    store.list_for_user.return_value = []
    store.get_for_user.return_value = None
    store.delete_for_user.return_value = True
    return store


@pytest.fixture
def anon_client(mock_graph, mock_store) -> TestClient:
    """Client without auth overridden (exercises 401)."""
    with (
        patch("api.main.build_checkpointer", return_value=MagicMock()),
        patch("api.main.build_store", return_value=MagicMock()),
        patch("api.main.build_graph", return_value=mock_graph),
        patch("api.main.open_pool", return_value=MagicMock()),
    ):
        app = create_app()
        app.dependency_overrides[get_chat_store] = lambda: mock_store
        with TestClient(app) as client:
            yield client


@pytest.fixture
def auth_client(mock_graph, mock_store) -> TestClient:
    """Client with auth overridden to a fixed user (exercises happy paths)."""
    with (
        patch("api.main.build_checkpointer", return_value=MagicMock()),
        patch("api.main.build_store", return_value=MagicMock()),
        patch("api.main.build_graph", return_value=mock_graph),
        patch("api.main.open_pool", return_value=MagicMock()),
    ):
        app = create_app()
        app.dependency_overrides[get_chat_store] = lambda: mock_store
        app.dependency_overrides[current_user] = lambda: User(id="user-1", email="a@b.co")
        with TestClient(app) as client:
            yield client


@pytest.fixture
def client(auth_client: TestClient) -> TestClient:
    """Default authenticated client for tests that expect auth."""
    return auth_client
