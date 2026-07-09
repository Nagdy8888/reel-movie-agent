"""Contract tests for the SSE chat endpoint."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_chat_requires_auth(anon_client: TestClient) -> None:
    """POST /chat returns 401 without a valid token."""
    response = anon_client.post("/chat", json={"message": "What movies did Tom Hanks act in?"})
    assert response.status_code == 401


def test_chat_streams_tokens_and_persists(auth_client: TestClient, mock_store: MagicMock) -> None:
    """Chat streams meta, token frames, done event, and persists user + assistant messages."""
    response = auth_client.post("/chat", json={"message": "What movies did Tom Hanks act in?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    body = response.text
    assert "event: meta" in body
    assert '"thread_id"' in body
    assert '"conversation_id"' in body
    assert '"token": "Hello"' in body
    assert "event: done" in body

    mock_store.upsert_conversation.assert_called_once()
    assert mock_store.add_message.call_count == 2
    conv_id = "11111111-1111-1111-1111-111111111111"
    msg = "What movies did Tom Hanks act in?"
    mock_store.add_message.assert_any_call(conv_id, "user", msg)
    mock_store.add_message.assert_any_call(conv_id, "assistant", "Hello")
    mock_store.touch.assert_called_once()


def test_chat_rejects_foreign_thread(auth_client: TestClient, mock_store: MagicMock) -> None:
    """POST /chat returns 403 when thread_id belongs to another user."""
    mock_store.upsert_conversation.return_value = None
    response = auth_client.post(
        "/chat",
        json={"message": "hi", "thread_id": "other-user-thread"},
    )
    assert response.status_code == 403


def test_chat_rejects_empty_message(auth_client: TestClient) -> None:
    """Chat rejects requests with an empty message."""
    response = auth_client.post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_responses_include_security_headers(auth_client: TestClient) -> None:
    """Every response carries security headers and X-Request-ID."""
    response = auth_client.get("/health")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Request-ID")
