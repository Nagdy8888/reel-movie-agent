"""Contract tests for the SSE chat endpoint."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_chat_requires_auth(anon_client: TestClient) -> None:
    """POST /chat returns 401 without a valid token."""
    response = anon_client.post("/chat", json={"message": "What movies did Tom Hanks act in?"})
    assert response.status_code == 401


def test_chat_streams_tokens_and_persists(auth_client: TestClient, mock_store: MagicMock) -> None:
    """Chat streams meta, token frames, done event, and persists user + assistant messages."""
    with patch(
        "api.routes.chat.generate_conversation_title",
        return_value="Tom Hanks Movies",
    ) as mock_title:
        response = auth_client.post("/chat", json={"message": "What movies did Tom Hanks act in?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    body = response.text
    assert "event: meta" in body
    assert '"thread_id"' in body
    assert '"conversation_id"' in body
    assert "event: sources" in body
    assert '"Forrest Gump"' in body
    assert "event: graph" in body
    assert '"Tom Hanks"' in body
    assert '"token": "Hello"' in body
    assert "event: done" in body

    mock_store.upsert_conversation.assert_called_once()
    assert mock_store.add_message.call_count == 2
    conv_id = "11111111-1111-1111-1111-111111111111"
    msg = "What movies did Tom Hanks act in?"
    mock_store.add_message.assert_any_call(conv_id, "user", msg)
    mock_store.add_message.assert_any_call(conv_id, "assistant", "Hello")
    mock_store.touch.assert_called_once()
    mock_title.assert_called_once_with(msg, "Hello")
    mock_store.update_title.assert_called_once_with(conv_id, "Tom Hanks Movies")


def test_chat_emits_artifacts_from_first_valid_values_event(
    auth_client: TestClient,
    mock_graph: MagicMock,
) -> None:
    """Artifacts should not depend on a preceding context-only values event."""

    def _stream_events(_inputs, _config, *, version):
        """Yield artifacts immediately, followed by one answer token."""
        del version
        yield {
            "method": "values",
            "params": {"data": {"sources": [], "graph": {"nodes": [], "links": []}}},
        }
        yield {
            "method": "values",
            "params": {
                "data": {
                    "context": "[Graph facts]\nThe Matrix",
                    "sources": [
                        {
                            "id": "movie:603",
                            "title": "The Matrix",
                            "subtitle": None,
                            "year": "1999",
                            "poster_url": None,
                            "tags": ["Keanu Reeves"],
                        }
                    ],
                    "graph": {
                        "nodes": [{"id": "movie:603", "label": "The Matrix", "type": "Movie"}],
                        "links": [],
                    },
                }
            },
        }
        yield {
            "method": "messages",
            "params": {
                "data": (
                    {
                        "event": "content-block-delta",
                        "delta": {"type": "text-delta", "text": "Watch The Matrix."},
                    },
                    {"langgraph_node": "generate"},
                )
            },
        }

    mock_graph.stream_events = _stream_events

    response = auth_client.post("/chat", json={"message": "Suggest a film"})

    assert response.status_code == 200
    assert response.text.count("event: sources") == 1
    assert response.text.count("event: graph") == 1
    assert '"movie:603"' in response.text


def test_chat_rejects_foreign_thread(auth_client: TestClient, mock_store: MagicMock) -> None:
    """POST /chat returns 403 when thread_id belongs to another user."""
    mock_store.upsert_conversation.return_value = None
    response = auth_client.post(
        "/chat",
        json={"message": "hi", "thread_id": "other-user-thread"},
    )
    assert response.status_code == 403


def test_chat_re_emits_filtered_sources_when_answer_cites_one_film(
    auth_client: TestClient,
    mock_store: MagicMock,
) -> None:
    """Sources/graph are narrowed after streaming when the answer cites one movie."""
    graph = MagicMock()

    def _stream_events(_inputs, _config, *, version):
        del version
        yield {
            "type": "event",
            "method": "values",
            "params": {"data": {"context": ""}},
            "seq": 0,
        }
        yield {
            "type": "event",
            "method": "values",
            "params": {
                "data": {
                    "context": "[Graph facts]\nForrest Gump",
                    "sources": [
                        {
                            "id": "movie-forrest-gump",
                            "title": "Forrest Gump",
                            "subtitle": None,
                            "year": "1994",
                            "tags": ["Tom Hanks"],
                        },
                        {
                            "id": "movie-the-matrix",
                            "title": "The Matrix",
                            "subtitle": None,
                            "year": "1999",
                            "tags": ["Keanu Reeves"],
                        },
                    ],
                    "graph": {"nodes": [], "links": []},
                }
            },
            "seq": 1,
        }
        yield {
            "type": "event",
            "method": "messages",
            "params": {
                "data": (
                    {
                        "event": "content-block-delta",
                        "index": 0,
                        "delta": {"type": "text-delta", "text": "Watch Forrest Gump."},
                    },
                    {"langgraph_node": "generate"},
                )
            },
            "seq": 2,
        }

    graph.stream_events = _stream_events

    with (
        patch("api.main.build_checkpointer", return_value=MagicMock()),
        patch("api.main.build_store", return_value=MagicMock()),
        patch("api.main.build_graph", return_value=graph),
        patch("api.main.open_pool", return_value=MagicMock()),
        patch("api.routes.chat.generate_conversation_title", return_value="Forrest Gump"),
    ):
        from api.auth import User, current_user
        from api.deps import get_chat_store
        from api.main import create_app

        app = create_app()
        app.dependency_overrides[get_chat_store] = lambda: mock_store
        app.dependency_overrides[current_user] = lambda: User(id="user-1", email="a@b.co")
        with TestClient(app) as client:
            response = client.post("/chat", json={"message": "suggest one film"})

    assert response.status_code == 200
    body = response.text
    sources_blocks = body.split("event: sources")[1:]
    assert len(sources_blocks) == 2
    filtered_block = sources_blocks[-1]
    assert "Forrest Gump" in filtered_block
    assert "The Matrix" not in filtered_block


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
