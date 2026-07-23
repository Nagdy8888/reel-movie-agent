"""Translate LangGraph events into resilient SSE chat streams."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any, cast

from fastapi import Request
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from agents.artifacts import GraphArtifact, SourceArtifact, filter_artifacts_by_answer
from api.schemas import ChatRequest
from api.services.chats import ChatStore
from api.services.titles import PLACEHOLDER_TITLE, generate_conversation_title
from api.settings import BackendSettings

logger = logging.getLogger("reel.chat")

_ANSWER_NODES = ("generate", "converse")


class ThreadOwnershipError(Exception):
    """Signal that a requested thread belongs to another user."""


class ClientDisconnectedError(Exception):
    """Signal that the streaming client disconnected before completion."""


def _answer_node_message(raw: dict[str, Any]) -> tuple[object, dict[str, Any]] | None:
    """Return the payload and metadata for an answer-node messages event."""
    if raw.get("method") != "messages":
        return None
    data = raw.get("params", {}).get("data")
    if not isinstance(data, tuple) or len(data) != 2:
        return None
    payload, metadata = data
    if not isinstance(metadata, dict) or metadata.get("langgraph_node") not in _ANSWER_NODES:
        return None
    return payload, metadata


def _token_from_v3_event(raw: dict[str, Any]) -> str:
    """Extract one streamed text token from a LangGraph v3 messages event."""
    message = _answer_node_message(raw)
    if message is None:
        return ""
    payload, _metadata = message
    if not isinstance(payload, dict) or payload.get("event") != "content-block-delta":
        return ""
    delta = payload.get("delta", {})
    if not isinstance(delta, dict) or delta.get("type") != "text-delta":
        return ""
    text = delta.get("text")
    return text if isinstance(text, str) else ""


def _message_text(content: object) -> str:
    """Flatten LangChain string or content-block message content."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _final_text_from_v3_event(raw: dict[str, Any]) -> str:
    """Extract a complete answer carried as a full message object."""
    message = _answer_node_message(raw)
    if message is None:
        return ""
    payload, _metadata = message
    if isinstance(payload, dict):
        return ""
    return _message_text(getattr(payload, "content", None))


def _artifacts_from_v3_event(
    raw: dict[str, Any],
) -> tuple[list[SourceArtifact], GraphArtifact] | None:
    """Extract source and graph artifacts from a LangGraph v3 values event."""
    if raw.get("method") != "values":
        return None
    data = raw.get("params", {}).get("data")
    if not isinstance(data, dict) or "sources" not in data:
        return None
    sources = data.get("sources")
    graph = data.get("graph")
    if not isinstance(sources, list) or not isinstance(graph, dict):
        return None
    return cast(list[SourceArtifact], sources), cast(GraphArtifact, graph)


def _errors_from_v3_event(raw: dict[str, Any]) -> list[str] | None:
    """Extract sanitized agent error codes from a LangGraph values event."""
    if raw.get("method") != "values":
        return None
    data = raw.get("params", {}).get("data")
    if not isinstance(data, dict) or "errors" not in data:
        return None
    errors = data.get("errors")
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
        return None
    return errors


class ChatStreamService:
    """Own chat-thread setup, graph event translation, and turn persistence."""

    def __init__(
        self,
        graph: CompiledStateGraph,
        store: ChatStore,
        settings: BackendSettings,
        request: Request,
    ) -> None:
        """Initialize one request-scoped chat stream service."""
        self._graph = graph
        self._store = store
        self._settings = settings
        self._request = request
        self._request_id = getattr(request.state, "request_id", "unknown")

    async def start(self, body: ChatRequest, user_id: str) -> AsyncIterator[str]:
        """Create or verify the thread, persist the user turn, and return its stream.

        Args:
            body: Validated chat input.
            user_id: Authenticated Supabase user id.

        Returns:
            Async SSE frame iterator.

        Raises:
            ThreadOwnershipError: If the thread belongs to another user.
        """
        thread_id = body.thread_id or str(uuid.uuid4())
        is_new_thread = body.thread_id is None
        conversation = await run_in_threadpool(
            self._store.upsert_conversation,
            user_id,
            thread_id,
            PLACEHOLDER_TITLE if is_new_thread else body.message[:60],
        )
        if conversation is None:
            raise ThreadOwnershipError
        conversation_id = str(conversation["id"])
        user_message_id = await run_in_threadpool(
            self._store.add_message,
            conversation_id,
            "user",
            body.message,
        )
        return self._stream(
            body,
            user_id,
            thread_id,
            conversation_id,
            user_message_id,
            is_new_thread=is_new_thread,
        )

    async def _stream(
        self,
        body: ChatRequest,
        user_id: str,
        thread_id: str,
        conversation_id: str,
        user_message_id: str,
        *,
        is_new_thread: bool,
    ) -> AsyncIterator[str]:
        """Stream one bounded agent turn and complete or roll back its persistence."""
        meta = json.dumps({"thread_id": thread_id, "conversation_id": conversation_id})
        yield f"event: meta\ndata: {meta}\n\n"

        parts: list[str] = []
        artifacts_flushed = False
        have_artifacts = False
        last_sources: list[SourceArtifact] = []
        last_graph: GraphArtifact = {"nodes": [], "links": []}
        last_agent_errors: list[str] = []
        fallback_answer = ""
        turn_completed = False
        stream: Iterator[dict[str, Any]] | None = None

        def artifact_frames() -> list[str]:
            """Serialize the freshest source and graph snapshots."""
            return [
                f"event: sources\ndata: {json.dumps({'sources': last_sources})}\n\n",
                f"event: graph\ndata: {json.dumps(last_graph)}\n\n",
            ]

        try:
            config: RunnableConfig = {
                "configurable": {"thread_id": thread_id},
                "run_name": "reel-chat",
                "tags": ["graphrag"],
                "metadata": {"thread_id": thread_id, "user_id": user_id},
            }
            inputs = {"messages": [HumanMessage(content=body.message)]}
            stream = cast(
                Iterator[dict[str, Any]],
                self._graph.stream_events(inputs, config, version="v3"),
            )

            async with asyncio.timeout(self._settings.chat_stream_timeout_seconds):
                async for raw in iterate_in_threadpool(stream):
                    if await self._request.is_disconnected():
                        raise ClientDisconnectedError
                    agent_errors = _errors_from_v3_event(raw)
                    if agent_errors is not None and agent_errors != last_agent_errors:
                        last_agent_errors = agent_errors
                        if agent_errors:
                            logger.warning(
                                "agent retrieval degraded",
                                extra={
                                    "request_id": self._request_id,
                                    "thread_id": thread_id,
                                    "error_count": len(agent_errors),
                                    "errors": agent_errors,
                                },
                            )
                    artifacts = _artifacts_from_v3_event(raw)
                    if artifacts is not None:
                        last_sources, last_graph = artifacts
                        have_artifacts = True
                    whole = _final_text_from_v3_event(raw)
                    if whole:
                        fallback_answer = whole
                    text = _token_from_v3_event(raw)
                    if text:
                        if not artifacts_flushed and have_artifacts:
                            for frame in artifact_frames():
                                yield frame
                            artifacts_flushed = True
                        parts.append(text)
                        yield f"data: {json.dumps({'token': text})}\n\n"

            if (
                not artifacts_flushed
                and have_artifacts
                and (last_sources or last_graph.get("nodes") or last_graph.get("links"))
            ):
                for frame in artifact_frames():
                    yield frame

            answer = "".join(parts)
            if not answer and fallback_answer:
                yield f"data: {json.dumps({'token': fallback_answer})}\n\n"
                answer = fallback_answer
            if not answer:
                raise RuntimeError("Graph completed without an answer")

            if last_sources:
                filtered = await run_in_threadpool(
                    filter_artifacts_by_answer,
                    last_sources,
                    last_graph,
                    answer,
                    question=body.message,
                )
                if filtered["sources"] != last_sources or filtered["graph"] != last_graph:
                    yield (
                        f"event: sources\ndata: {json.dumps({'sources': filtered['sources']})}\n\n"
                    )
                    yield f"event: graph\ndata: {json.dumps(filtered['graph'])}\n\n"

            title = await self._generate_title(body.message, answer, is_new_thread)
            await run_in_threadpool(
                self._store.complete_turn,
                conversation_id,
                answer,
                title=title,
            )
            turn_completed = True
            yield "event: done\ndata: {}\n\n"
        except ClientDisconnectedError:
            await self._rollback_user_turn(conversation_id, user_message_id, turn_completed)
            logger.info("chat client disconnected", extra={"request_id": self._request_id})
        except TimeoutError:
            await self._rollback_user_turn(conversation_id, user_message_id, turn_completed)
            logger.warning("chat stream timed out", extra={"request_id": self._request_id})
            for frame in self._error_frames("timeout"):
                yield frame
        except asyncio.CancelledError:
            await asyncio.shield(
                self._rollback_user_turn(conversation_id, user_message_id, turn_completed)
            )
            logger.info("chat stream cancelled", extra={"request_id": self._request_id})
            raise
        except Exception:
            await self._rollback_user_turn(conversation_id, user_message_id, turn_completed)
            logger.exception("chat stream failed", extra={"request_id": self._request_id})
            for frame in self._error_frames("stream_failed"):
                yield frame
        finally:
            if stream is not None:
                await self._close_stream(stream)

    async def _generate_title(
        self,
        question: str,
        answer: str,
        is_new_thread: bool,
    ) -> str | None:
        """Generate a new-thread title without failing an otherwise valid answer."""
        if not is_new_thread:
            return None
        try:
            return await run_in_threadpool(
                generate_conversation_title,
                question,
                answer[:400],
            )
        except Exception:
            logger.exception(
                "conversation title generation failed",
                extra={"request_id": self._request_id},
            )
            return None

    async def _rollback_user_turn(
        self,
        conversation_id: str,
        user_message_id: str,
        turn_completed: bool,
    ) -> None:
        """Remove an incomplete user turn while preserving prior conversation history."""
        if turn_completed:
            return
        try:
            await run_in_threadpool(
                self._store.delete_user_message,
                conversation_id,
                user_message_id,
            )
        except Exception:
            logger.exception(
                "chat turn rollback failed",
                extra={"request_id": self._request_id},
            )

    def _error_frames(self, code: str) -> list[str]:
        """Return a generic client-safe error event followed by stream completion."""
        payload = json.dumps(
            {
                "code": code,
                "detail": "Unable to complete the chat response",
                "request_id": self._request_id,
            }
        )
        return [f"event: error\ndata: {payload}\n\n", "event: done\ndata: {}\n\n"]

    async def _close_stream(self, stream: Iterator[dict[str, Any]]) -> None:
        """Best-effort close the underlying synchronous graph iterator."""
        close = getattr(stream, "close", None)
        if not callable(close):
            return
        try:
            await run_in_threadpool(close)
        except (RuntimeError, ValueError):
            logger.debug(
                "graph stream could not close immediately",
                extra={"request_id": self._request_id},
            )
