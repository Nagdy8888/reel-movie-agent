"""Persistence for user conversations and messages (Supabase Postgres)."""

from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg_pool import ConnectionPool


class ChatStore:
    """CRUD for conversations and messages, always scoped to a user."""

    def __init__(self, pool: ConnectionPool[Connection[DictRow]]) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    def upsert_conversation(
        self, user_id: str, thread_id: str, title: str
    ) -> dict[str, Any] | None:
        """Insert or touch a conversation.

        Returns the row, or None if the thread already exists under a different
        user (caller should treat that as 403).
        """
        with self._pool.connection() as conn:
            return conn.execute(
                """
                INSERT INTO conversations (user_id, thread_id, title)
                VALUES (%s, %s, %s)
                ON CONFLICT (thread_id) DO UPDATE SET updated_at = now()
                WHERE conversations.user_id = EXCLUDED.user_id
                RETURNING id, user_id, thread_id, title, created_at, updated_at
                """,
                (user_id, thread_id, title),
            ).fetchone()

    def add_message(self, conversation_id: str, role: str, content: str) -> str:
        """Append a message row and return its generated id."""
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (conversation_id, role, content),
            ).fetchone()
        if row is None:
            raise RuntimeError("Message insert did not return an id")
        return str(row["id"])

    def delete_user_message(self, conversation_id: str, message_id: str) -> None:
        """Delete one incomplete user turn without touching prior history."""
        with self._pool.connection() as conn:
            conn.execute(
                """
                DELETE FROM messages
                WHERE id = %s AND conversation_id = %s AND role = 'user'
                """,
                (message_id, conversation_id),
            )

    def complete_turn(
        self,
        conversation_id: str,
        answer: str,
        *,
        title: str | None = None,
    ) -> None:
        """Persist the assistant reply and conversation metadata atomically."""
        with self._pool.connection() as conn, conn.transaction():
            conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content)
                VALUES (%s, 'assistant', %s)
                """,
                (conversation_id, answer),
            )
            if title is None:
                conn.execute(
                    "UPDATE conversations SET updated_at = now() WHERE id = %s",
                    (conversation_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE conversations
                    SET title = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (title, conversation_id),
                )

    def touch(self, conversation_id: str) -> None:
        """Bump a conversation's updated_at."""
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = now() WHERE id = %s",
                (conversation_id,),
            )

    def update_title(self, conversation_id: str, title: str) -> None:
        """Set the sidebar title for a conversation."""
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE conversations SET title = %s WHERE id = %s",
                (title, conversation_id),
            )

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Return the user's conversations, newest first."""
        with self._pool.connection() as conn:
            return conn.execute(
                """
                SELECT id, thread_id, title, created_at, updated_at
                FROM conversations WHERE user_id = %s ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()

    def get_for_user(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        """Return one conversation with ordered messages, or None if not owned."""
        with self._pool.connection() as conn:
            conv = conn.execute(
                """
                SELECT id, thread_id, title, created_at, updated_at
                FROM conversations WHERE id = %s AND user_id = %s
                """,
                (conversation_id, user_id),
            ).fetchone()
            if conv is None:
                return None
            conv["messages"] = conn.execute(
                """
                SELECT role, content, created_at FROM messages
                WHERE conversation_id = %s ORDER BY created_at
                """,
                (conversation_id,),
            ).fetchall()
        return conv

    def delete_for_user(self, user_id: str, conversation_id: str) -> bool:
        """Delete a conversation (messages cascade). Returns True if a row was removed."""
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
        return cur.rowcount > 0
