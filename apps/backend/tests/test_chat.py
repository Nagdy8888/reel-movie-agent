"""Contract tests for the SSE chat endpoint."""

import json
import logging
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_chat_logs_sanitized_agent_errors(auth_client: TestClient, caplog) -> None:
    """Retrieval degradation is correlated in backend logs, not sent to clients."""

    def _stream_events(_inputs, _config, *, version):
        """Emit one degraded state followed by a complete answer."""
        del version
        yield {
            "method": "values",
            "params": {
                "data": {
                    "errors": ["hybrid_context:TimeoutError"],
                    "sources": [],
                    "graph": {"nodes": [], "links": []},
                }
            },
        }
        yield {
            "method": "messages",
            "params": {
                "data": (
                    {
                        "event": "content-block-delta",
                        "delta": {"type": "text-delta", "text": "Grounded answer"},
                    },
                    {"langgraph_node": "generate"},
                )
            },
        }

    auth_client.app.state.graph.stream_events = _stream_events
    with (
        patch("api.services.streaming.generate_conversation_title", return_value="Answer"),
        caplog.at_level(logging.WARNING, logger="reel.chat"),
    ):
        response = auth_client.post("/chat", json={"message": "Suggest a movie"})

    records = [record for record in caplog.records if record.message == "agent retrieval degraded"]
    assert len(records) == 1
    assert records[0].errors == ["hybrid_context:TimeoutError"]
    assert "TimeoutError" not in response.text


def test_chat_requires_auth(anon_client: TestClient) -> None:
    """POST /chat returns 401 without a valid token."""
    response = anon_client.post("/chat", json={"message": "What movies did Tom Hanks act in?"})
    assert response.status_code == 401


def test_chat_streams_tokens_and_persists(auth_client: TestClient, mock_store: MagicMock) -> None:
    """Chat streams meta, token frames, done event, and persists user + assistant messages."""
    with patch(
        "api.services.streaming.generate_conversation_title",
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
    conv_id = "11111111-1111-1111-1111-111111111111"
    msg = "What movies did Tom Hanks act in?"
    mock_store.add_message.assert_called_once_with(conv_id, "user", msg)
    mock_title.assert_called_once_with(msg, "Hello")
    mock_store.complete_turn.assert_called_once_with(
        conv_id,
        "Hello",
        title="Tom Hanks Movies",
    )


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


def test_chat_emits_fresh_artifacts_over_stale_checkpoint_values(
    auth_client: TestClient,
) -> None:
    """A resumed thread must stream the current turn's artifacts, not the prior turn's.

    The checkpointer persists ``sources``/``graph`` across turns, so early values
    snapshots on a follow-up question still carry the previous answer's artifacts.
    The stream must flush the *freshest* snapshot (after ``retrieve``), so the UI
    poster and subgraph update instead of freezing on the first answer.
    """
    stale = {
        "sources": [{"id": "movie:1", "title": "The Hunger Games", "tags": []}],
        "graph": {
            "nodes": [{"id": "movie:1", "label": "The Hunger Games", "type": "Movie"}],
            "links": [],
        },
    }
    fresh = {
        "sources": [{"id": "movie:2", "title": "Arrival", "tags": []}],
        "graph": {
            "nodes": [{"id": "movie:2", "label": "Arrival", "type": "Movie"}],
            "links": [],
        },
    }

    def _stream_events(_inputs, _config, *, version):
        """Carry stale artifacts first (checkpoint), then the fresh retrieve output."""
        del version
        yield {"method": "values", "params": {"data": {"context": "old", **stale}}}
        yield {"method": "values", "params": {"data": {"context": "old", **stale}}}
        yield {
            "method": "values",
            "params": {"data": {"context": "[Graph facts]\nArrival", **fresh}},
        }
        yield {
            "method": "messages",
            "params": {
                "data": (
                    {
                        "event": "content-block-delta",
                        "delta": {"type": "text-delta", "text": "Watch Arrival."},
                    },
                    {"langgraph_node": "generate"},
                )
            },
        }

    from api.deps import get_graph

    fake_graph = MagicMock()
    fake_graph.stream_events = _stream_events
    auth_client.app.dependency_overrides[get_graph] = lambda: fake_graph
    try:
        with patch("api.services.streaming.generate_conversation_title", return_value="Sci-fi"):
            response = auth_client.post(
                "/chat",
                json={"message": "sci-fi movies about survival", "thread_id": "thread-1"},
            )
    finally:
        auth_client.app.dependency_overrides.pop(get_graph, None)

    assert response.status_code == 200
    body = response.text
    first_sources_block = body.split("event: sources")[1]
    assert "Arrival" in first_sources_block
    assert "The Hunger Games" not in first_sources_block


def test_chat_emits_whole_message_reply_when_no_tokens_stream(
    auth_client: TestClient,
    mock_store: MagicMock,
) -> None:
    """A reply returned as a whole message (fail-closed answer) is still shown/saved.

    Statically built answers arrive as a full ``AIMessage`` in one ``messages``
    frame rather than ``content-block-delta`` chunks. The stream must surface the
    text as a token and persist it instead of crashing or ending silently.
    """
    from langchain_core.messages import AIMessage

    reply = "I don't have grounded information about that movie."

    def _stream_events(_inputs, _config, *, version):
        """Empty artifacts, then a whole-message reply with no streamed delta."""
        del version
        yield {
            "method": "values",
            "params": {"data": {"sources": [], "graph": {"nodes": [], "links": []}}},
        }
        yield {
            "method": "messages",
            "params": {"data": (AIMessage(content=reply), {"langgraph_node": "generate"})},
        }

    auth_client.app.state.graph.stream_events = _stream_events

    with patch("api.services.streaming.generate_conversation_title", return_value="Unknown film"):
        response = auth_client.post("/chat", json={"message": "Tell me about a fake movie"})

    assert response.status_code == 200
    assert f'"token": {json.dumps(reply)}' in response.text
    mock_store.complete_turn.assert_called_once_with(
        "11111111-1111-1111-1111-111111111111",
        reply,
        title="Unknown film",
    )


def test_chat_rejects_foreign_thread(auth_client: TestClient, mock_store: MagicMock) -> None:
    """POST /chat returns 403 when thread_id belongs to another user."""
    mock_store.upsert_conversation.return_value = None
    response = auth_client.post(
        "/chat",
        json={"message": "hi", "thread_id": "other-user-thread"},
    )
    assert response.status_code == 403


def test_chat_emits_error_and_rolls_back_failed_turn(
    auth_client: TestClient,
    mock_graph: MagicMock,
    mock_store: MagicMock,
) -> None:
    """A graph failure emits a safe error frame and removes the orphan user turn."""

    def _stream_events(_inputs, _config, *, version):
        """Raise before the graph can produce an answer."""
        del version
        raise RuntimeError("private upstream detail")
        yield

    mock_graph.stream_events = _stream_events

    response = auth_client.post("/chat", json={"message": "Suggest a movie"})

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"code": "stream_failed"' in response.text
    assert "private upstream detail" not in response.text
    assert response.text.endswith("event: done\ndata: {}\n\n")
    mock_store.delete_user_message.assert_called_once_with(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )
    mock_store.complete_turn.assert_not_called()


def test_chat_enforces_overall_stream_timeout(
    auth_client: TestClient,
    mock_graph: MagicMock,
    mock_store: MagicMock,
) -> None:
    """A graph that exceeds the turn budget emits timeout and rolls back."""
    from api.settings import BackendSettings, get_settings

    def _slow_stream(_inputs, _config, *, version):
        """Block longer than the configured test deadline."""
        del version
        time.sleep(0.05)
        yield {
            "method": "messages",
            "params": {
                "data": (
                    {
                        "event": "content-block-delta",
                        "delta": {"type": "text-delta", "text": "late"},
                    },
                    {"langgraph_node": "generate"},
                )
            },
        }

    mock_graph.stream_events = _slow_stream
    auth_client.app.dependency_overrides[get_settings] = lambda: BackendSettings(
        chat_stream_timeout_seconds=0.01
    )
    try:
        response = auth_client.post("/chat", json={"message": "Suggest a movie"})
    finally:
        auth_client.app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    assert '"code": "timeout"' in response.text
    assert '"token": "late"' not in response.text
    mock_store.delete_user_message.assert_called_once()


def test_chat_rate_limit_returns_429(
    auth_client: TestClient,
) -> None:
    """The paid chat endpoint rejects requests after its per-minute budget."""
    from api.limiter import limiter

    limiter.reset()
    try:
        responses = [
            auth_client.post(
                "/chat",
                json={"message": "hi", "thread_id": f"rate-thread-{index}"},
            )
            for index in range(21)
        ]
    finally:
        limiter.reset()

    assert all(response.status_code == 200 for response in responses[:20])
    assert responses[20].status_code == 429


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
        patch("api.services.streaming.generate_conversation_title", return_value="Forrest Gump"),
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


def test_chat_filters_by_question_when_answer_omits_title(
    auth_client: TestClient,
    mock_store: MagicMock,
) -> None:
    """Cast answers without the film title still filter via the question."""
    graph = MagicMock()

    def _stream_events(_inputs, _config, *, version):
        del version
        yield {
            "type": "event",
            "method": "values",
            "params": {
                "data": {
                    "context": "facts",
                    "sources": [
                        {
                            "id": "movie:31186339",
                            "title": "The Hunger Games",
                            "subtitle": None,
                            "year": "2012",
                            "tags": [],
                        },
                        {
                            "id": "movie:603",
                            "title": "The Matrix",
                            "subtitle": None,
                            "year": "1999",
                            "tags": [],
                        },
                    ],
                    "graph": {
                        "nodes": [
                            {
                                "id": "movie:31186339",
                                "label": "The Hunger Games",
                                "type": "Movie",
                            },
                            {"id": "movie:603", "label": "The Matrix", "type": "Movie"},
                        ],
                        "links": [],
                    },
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
                        "delta": {
                            "type": "text-delta",
                            "text": "Jennifer Lawrence as Katniss Everdeen.",
                        },
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
        patch("api.services.streaming.generate_conversation_title", return_value="Hunger Games"),
    ):
        from api.auth import User, current_user
        from api.deps import get_chat_store
        from api.main import create_app

        app = create_app()
        app.dependency_overrides[get_chat_store] = lambda: mock_store
        app.dependency_overrides[current_user] = lambda: User(id="user-1", email="a@b.co")
        with TestClient(app) as client:
            response = client.post(
                "/chat",
                json={"message": "Who starred in The Hunger Games?"},
            )

    assert response.status_code == 200
    filtered_block = response.text.split("event: sources")[-1]
    assert "The Hunger Games" in filtered_block
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
