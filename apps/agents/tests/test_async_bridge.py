"""Tests for the persistent sync-to-async runtime."""

import asyncio
import threading

from agents.async_bridge import run_sync


async def _runtime_identity() -> tuple[int, int]:
    """Return the current event-loop and thread identities."""
    return id(asyncio.get_running_loop()), threading.get_ident()


def test_run_sync_reuses_one_event_loop_and_thread() -> None:
    """Cached async clients always run on the same background event loop."""
    first = run_sync(_runtime_identity())
    second = run_sync(_runtime_identity())
    assert first == second
