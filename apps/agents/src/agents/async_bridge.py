"""Bridge async LightRAG / asyncpg coroutines into sync agent nodes."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from functools import lru_cache
from threading import Event, Thread
from typing import TypeVar

T = TypeVar("T")


class _AsyncRuntime:
    """Own one persistent event loop for sync-to-async agent calls."""

    def __init__(self) -> None:
        """Start the daemon thread and wait until its event loop is ready."""
        self._ready = Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = Thread(
            target=self._run,
            name="reel-async-runtime",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        """Create and run the background event loop forever."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()

    def submit(self, coro: Coroutine[object, object, T]) -> T:
        """Run a coroutine on the persistent loop and return its result."""
        if self._loop is None:
            raise RuntimeError("Async runtime failed to initialize")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()


@lru_cache(maxsize=1)
def _runtime() -> _AsyncRuntime:
    """Return the process-wide async runtime."""
    return _AsyncRuntime()


def run_sync(coro: Coroutine[object, object, T]) -> T:
    """Run ``coro`` to completion from sync code.

    LangGraph nodes are synchronous, while LightRAG's PostgreSQL clients are
    asynchronous and event-loop-bound. A single background event loop keeps
    the cached LightRAG instance on the same loop across every tool call.

    Args:
        coro: Coroutine to await.

    Returns:
        The coroutine's result.
    """
    return _runtime().submit(coro)
