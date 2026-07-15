"""Bridge async LightRAG / asyncpg coroutines into sync agent nodes."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[object, object, T]) -> T:
    """Run ``coro`` to completion from sync code.

    LangGraph nodes and FastAPI ``run_in_threadpool`` callers are sync. When no
    event loop is running, use ``asyncio.run``. When one is already running
    (unusual for this stack), run the coroutine in a worker thread.

    Args:
        coro: Coroutine to await.

    Returns:
        The coroutine's result.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
