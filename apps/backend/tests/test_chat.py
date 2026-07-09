"""Contract tests for the SSE chat endpoint."""

from fastapi.testclient import TestClient


def test_chat_streams_tokens_and_done(client: TestClient) -> None:
    """Chat streams meta, token frames, and a done event."""
    response = client.post("/chat", json={"message": "What movies did Tom Hanks act in?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    body = response.text
    assert "event: meta" in body
    assert '"thread_id"' in body
    assert '"token": "Hello"' in body
    assert "event: done" in body


def test_chat_rejects_empty_message(client: TestClient) -> None:
    """Chat rejects requests with an empty message."""
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 422
