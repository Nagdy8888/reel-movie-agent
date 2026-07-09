"""Contract tests for chat history endpoints."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

from fastapi.testclient import TestClient

_CONV_ID = "11111111-1111-1111-1111-111111111111"
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_list_chats_requires_auth(anon_client: TestClient) -> None:
    """GET /chats returns 401 without a valid token."""
    response = anon_client.get("/chats")
    assert response.status_code == 401


def test_list_chats_returns_summaries(auth_client: TestClient, mock_store: MagicMock) -> None:
    """GET /chats returns the authenticated user's conversations."""
    mock_store.list_for_user.return_value = [
        {
            "id": _CONV_ID,
            "thread_id": "thread-1",
            "title": "Hello",
            "created_at": _NOW,
            "updated_at": _NOW,
        }
    ]
    response = auth_client.get("/chats")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["thread_id"] == "thread-1"
    mock_store.list_for_user.assert_called_once_with("user-1")


def test_get_chat_returns_detail(auth_client: TestClient, mock_store: MagicMock) -> None:
    """GET /chats/{id} returns conversation with messages when owned."""
    mock_store.get_for_user.return_value = {
        "id": _CONV_ID,
        "thread_id": "thread-1",
        "title": "Hello",
        "created_at": _NOW,
        "updated_at": _NOW,
        "messages": [
            {"role": "user", "content": "hi", "created_at": _NOW},
            {"role": "assistant", "content": "Hello", "created_at": _NOW},
        ],
    }
    response = auth_client.get(f"/chats/{_CONV_ID}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["messages"]) == 2
    mock_store.get_for_user.assert_called_once_with("user-1", _CONV_ID)


def test_get_chat_not_found(auth_client: TestClient, mock_store: MagicMock) -> None:
    """GET /chats/{id} returns 404 when conversation is not owned."""
    mock_store.get_for_user.return_value = None
    response = auth_client.get(f"/chats/{UUID(int=0)}")
    assert response.status_code == 404


def test_delete_chat_returns_204(auth_client: TestClient, mock_store: MagicMock) -> None:
    """DELETE /chats/{id} returns 204 when conversation is deleted."""
    response = auth_client.delete(f"/chats/{_CONV_ID}")
    assert response.status_code == 204
    mock_store.delete_for_user.assert_called_once_with("user-1", _CONV_ID)


def test_delete_chat_not_found(auth_client: TestClient, mock_store: MagicMock) -> None:
    """DELETE /chats/{id} returns 404 when conversation is not owned."""
    mock_store.delete_for_user.return_value = False
    response = auth_client.delete(f"/chats/{UUID(int=0)}")
    assert response.status_code == 404
