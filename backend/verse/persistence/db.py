from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path
from sqlite3 import Connection, Row, connect
from threading import RLock
from typing import Any


DEFAULT_DB_PATH = Path("~/.verse/history.db").expanduser()


@dataclass(frozen=True)
class Message:
    id: int
    conv_id: int
    role: str
    content: str
    tool_calls: Any
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conv_id": self.conv_id,
            "role": self.role,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "created_at": self.created_at,
        }


class ConversationStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path).expanduser()
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = connect(self.db_path)
        self._connection.row_factory = Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def new_conversation(self) -> int:
        now = _utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO conversations (started_at) VALUES (?)",
                (now,),
            )
            return int(cursor.lastrowid)

    def end_conversation(self, conv_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE conversations SET ended_at = ? WHERE id = ?",
                (_utc_now(), conv_id),
            )

    def save_message(
        self,
        conv_id: int,
        role: str,
        content: str,
        *,
        tool_calls: Any = None,
    ) -> int:
        created_at = _utc_now()
        serialized_tool_calls = (
            None if tool_calls is None else json.dumps(tool_calls, ensure_ascii=True)
        )
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO messages (conv_id, role, content, tool_calls, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conv_id, role, content, serialized_tool_calls, created_at),
            )
            return int(cursor.lastrowid)

    def load_recent_messages(
        self,
        *,
        limit: int = 10,
        conv_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            return []

        params: tuple[Any, ...]
        if conv_id is None:
            query = """
                SELECT id, conv_id, role, content, tool_calls, created_at
                FROM messages
                ORDER BY id DESC
                LIMIT ?
            """
            params = (limit,)
        else:
            query = """
                SELECT id, conv_id, role, content, tool_calls, created_at
                FROM messages
                WHERE conv_id = ?
                ORDER BY id DESC
                LIMIT ?
            """
            params = (conv_id, limit)

        with self._lock:
            rows = self._connection.execute(query, params).fetchall()

        return [_row_to_message(row).as_dict() for row in reversed(rows)]

    def upsert_memory(self, content: str, *, salience: float = 1.0) -> int | None:
        """Store a durable fact about the user. De-duplicates on normalized text;
        a repeated fact just bumps salience/updated_at instead of inserting again.
        Returns the row id, or None if the content is blank."""
        content = content.strip()
        norm = _normalize_memory(content)
        if not norm:
            return None
        now = _utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO memories (content, content_norm, salience, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(content_norm) DO UPDATE SET
                    salience = MAX(memories.salience, excluded.salience) + 0.1,
                    updated_at = excluded.updated_at
                """,
                (content, norm, salience, now),
            )
            row = self._connection.execute(
                "SELECT id FROM memories WHERE content_norm = ?", (norm,)
            ).fetchone()
            return int(row["id"]) if row else int(cursor.lastrowid)

    def load_memories(self, *, limit: int = 20) -> list[str]:
        """Return the most salient/recent durable facts, highest priority first."""
        if limit < 1:
            return []
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT content FROM memories
                ORDER BY salience DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [str(row["content"]) for row in rows]

    def prune_memories(self, *, max_count: int) -> int:
        """Keep only the top `max_count` facts (by salience then recency); delete
        the rest. Returns how many were removed."""
        if max_count < 0:
            return 0
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                DELETE FROM memories
                WHERE id NOT IN (
                    SELECT id FROM memories
                    ORDER BY salience DESC, updated_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (max_count,),
            )
            return int(cursor.rowcount)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _ensure_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conv_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conv_id) REFERENCES conversations(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conv_id_id
                    ON messages (conv_id, id);
                CREATE INDEX IF NOT EXISTS idx_messages_id
                    ON messages (id);

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    content_norm TEXT NOT NULL UNIQUE,
                    salience REAL NOT NULL DEFAULT 1.0,
                    updated_at TEXT NOT NULL
                );
                """
            )


@lru_cache(maxsize=1)
def default_store() -> ConversationStore:
    return ConversationStore()


def new_conversation() -> int:
    return default_store().new_conversation()


def save_message(
    conv_id: int,
    role: str,
    content: str,
    *,
    tool_calls: Any = None,
) -> int:
    return default_store().save_message(
        conv_id,
        role,
        content,
        tool_calls=tool_calls,
    )


def load_recent_messages(limit: int = 10) -> list[dict[str, Any]]:
    return default_store().load_recent_messages(limit=limit)


def _row_to_message(row: Row) -> Message:
    tool_calls = row["tool_calls"]
    return Message(
        id=int(row["id"]),
        conv_id=int(row["conv_id"]),
        role=str(row["role"]),
        content=str(row["content"]),
        tool_calls=None if tool_calls is None else json.loads(tool_calls),
        created_at=str(row["created_at"]),
    )


def _normalize_memory(content: str) -> str:
    """Collapse whitespace + lowercase so trivially-different phrasings of the same
    fact de-duplicate. Used only as the UNIQUE dedup key, not for display."""
    return " ".join(content.lower().split())


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
