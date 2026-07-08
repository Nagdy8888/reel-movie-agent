"""Postgres-backed checkpointer and store for agent memory."""

from functools import lru_cache
from typing import cast

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from agents.settings import get_settings


@lru_cache(maxsize=1)
def _get_pool() -> ConnectionPool[Connection[DictRow]]:
    """Return a long-lived Postgres connection pool for memory backends.

    ``PostgresSaver.from_conn_string`` / ``PostgresStore.from_conn_string`` are
    context managers that close the connection on exit; a cached pool keeps
    connections open for the process lifetime (backend Phase 5).
    """
    settings = get_settings()
    return ConnectionPool(
        conninfo=settings.supabase_db_url,
        min_size=1,
        max_size=5,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        open=True,
    )


def build_checkpointer() -> PostgresSaver:
    """Create and set up a Postgres checkpointer (Supabase Postgres).

    Side effects: runs ``.setup()`` (creates checkpoint tables if absent).
    """
    saver = PostgresSaver(conn=cast(ConnectionPool[Connection[DictRow]], _get_pool()))
    saver.setup()
    return saver


def build_store() -> PostgresStore:
    """Create and set up a Postgres cross-conversation store.

    Side effects: runs ``.setup()`` (creates store tables if absent).
    """
    store = PostgresStore(conn=cast(ConnectionPool[Connection[DictRow]], _get_pool()))
    store.setup()
    return store
