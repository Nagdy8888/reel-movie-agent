"""Sync Postgres connection pool for backend chat persistence."""

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from api.settings import get_settings


def open_pool() -> ConnectionPool[Connection[DictRow]]:
    """Open and return a Postgres pool for the chat tables.

    Opened eagerly in the app lifespan and closed on shutdown.
    """
    settings = get_settings()
    return ConnectionPool(
        conninfo=settings.supabase_db_url,
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
