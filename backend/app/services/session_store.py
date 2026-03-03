"""SQLite persistence for sessions, messages, and hook events.

Uses aiosqlite for async operations. The database file lives at
backend/nexus_v2.db (next to the app/ package).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent.parent / "nexus_v2.db"

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    claude_session_id TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    role            TEXT,
    project_name    TEXT,
    project_dir     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    tool_calls  TEXT,
    thinking    TEXT,
    is_complete BOOLEAN NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hook_events (
    id          TEXT PRIMARY KEY,
    session_id  TEXT,
    event_type  TEXT,
    tool_name   TEXT,
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_hook_events_session ON hook_events(session_id);
"""


async def init_db() -> None:
    """Create tables if they don't exist."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.executescript(_CREATE_TABLES)
        await db.commit()

        # Migrate: add new columns if they don't exist (for existing databases)
        for col in ["role", "project_name", "project_dir"]:
            try:
                await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")
                await db.commit()
            except Exception:
                pass  # Column already exists

    logger.info("SQLite database initialized at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _row_to_dict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict:
    """Convert a Row to a dict using column names."""
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

async def create_session(
    title: Optional[str] = None,
    role: Optional[str] = None,
    project_name: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> dict:
    now = _now()
    session = {
        "id": _uuid(),
        "title": title or "New Session",
        "claude_session_id": _uuid(),
        "status": "active",
        "role": role,
        "project_name": project_name,
        "project_dir": project_dir,
        "created_at": now,
        "updated_at": now,
    }
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """INSERT INTO sessions (id, title, claude_session_id, status, role, project_name, project_dir, created_at, updated_at)
               VALUES (:id, :title, :claude_session_id, :status, :role, :project_name, :project_dir, :created_at, :updated_at)""",
            session,
        )
        await db.commit()
    return session


async def list_sessions() -> list[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = _row_to_dict  # type: ignore[assignment]
        cursor = await db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
    return rows  # type: ignore[return-value]


async def get_session(session_id: str) -> Optional[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = _row_to_dict  # type: ignore[assignment]
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
    return row  # type: ignore[return-value]


async def get_session_detail(session_id: str) -> Optional[dict]:
    """Get session with its messages."""
    session = await get_session(session_id)
    if not session:
        return None
    messages = await list_messages(session_id)
    session["messages"] = messages
    return session


async def delete_session(session_id: str) -> bool:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        # Delete messages first (foreign key)
        await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor = await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()
        return cursor.rowcount > 0


async def touch_session(session_id: str) -> None:
    """Update the updated_at timestamp."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def create_message(
    session_id: str,
    role: str,
    content: str,
    tool_calls: Optional[str] = None,
    thinking: Optional[str] = None,
    is_complete: bool = True,
) -> dict:
    now = _now()
    msg = {
        "id": _uuid(),
        "session_id": session_id,
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
        "thinking": thinking,
        "is_complete": is_complete,
        "created_at": now,
    }
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """INSERT INTO messages (id, session_id, role, content, tool_calls, thinking, is_complete, created_at)
               VALUES (:id, :session_id, :role, :content, :tool_calls, :thinking, :is_complete, :created_at)""",
            msg,
        )
        await db.commit()
    # Touch parent session
    await touch_session(session_id)
    return msg


async def update_message(message_id: str, **fields) -> None:
    """Update specific fields on a message."""
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [message_id]
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            f"UPDATE messages SET {set_clause} WHERE id = ?",
            values,
        )
        await db.commit()


async def list_messages(session_id: str, limit: int = 100) -> list[dict]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = _row_to_dict  # type: ignore[assignment]
        cursor = await db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
    # Deserialize tool_calls from JSON string to list
    for row in rows:
        if row.get("tool_calls") and isinstance(row["tool_calls"], str):
            try:
                row["tool_calls"] = json.loads(row["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                row["tool_calls"] = []
    return rows  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Hook Events
# ---------------------------------------------------------------------------

async def create_hook_event(
    event_type: Optional[str] = None,
    session_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    payload: Optional[dict] = None,
) -> dict:
    now = _now()
    evt = {
        "id": _uuid(),
        "session_id": session_id,
        "event_type": event_type,
        "tool_name": tool_name,
        "payload": json.dumps(payload or {}),
        "created_at": now,
    }
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            """INSERT INTO hook_events (id, session_id, event_type, tool_name, payload, created_at)
               VALUES (:id, :session_id, :event_type, :tool_name, :payload, :created_at)""",
            evt,
        )
        await db.commit()
    return evt
