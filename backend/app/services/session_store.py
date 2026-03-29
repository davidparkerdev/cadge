"""SQLite persistence for sessions, messages, and hook events.

Uses aiosqlite for async operations. The database file lives at
backend/cadge.db (next to the app/ package).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    _HAS_PILLOW = True
except ImportError:
    _HAS_PILLOW = False

_MAX_THUMBNAIL_WIDTH = 400
_MAX_THUMBNAIL_QUALITY = 60
_FALLBACK_MAX_BYTES = 200 * 1024

from contextlib import asynccontextmanager

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent.parent / "cadge.db"

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
    provider_id     TEXT NOT NULL DEFAULT 'claude-code',
    model           TEXT,
    provider_session_id TEXT,
    provider_initialized BOOLEAN NOT NULL DEFAULT 0,
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
    status      TEXT NOT NULL DEFAULT 'complete',
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
    async with _connect_db() as db:
        await db.executescript(_CREATE_TABLES)
        await db.commit()

        # Enable WAL mode for concurrent read/write access.
        # Eliminates "database is locked" errors under load.
        await db.execute("PRAGMA journal_mode=WAL;")
        # Enable foreign key enforcement so ON DELETE CASCADE actually works.
        # SQLite has FK support compiled in but OFF by default per-connection.
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.commit()

        # Migrate: add new columns if they don't exist (for existing databases)
        for col in ["role", "project_name", "project_dir"]:
            try:
                await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")
                await db.commit()
            except Exception:
                pass  # Column already exists

        # Migrate: add status column to messages if it doesn't exist
        try:
            await db.execute(
                "ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'"
            )
            await db.commit()
        except Exception:
            pass  # Column already exists

        # Migrate: add claude_initialized flag to sessions
        try:
            await db.execute(
                "ALTER TABLE sessions ADD COLUMN claude_initialized BOOLEAN NOT NULL DEFAULT 0"
            )
            await db.commit()
        except Exception:
            pass  # Column already exists

        # Migrate: add provider columns to sessions
        for col, default in [
            ("provider_id", "'claude-code'"),
            ("model", "NULL"),
            ("provider_session_id", "NULL"),
            ("provider_initialized", "0"),
        ]:
            try:
                if default == "NULL":
                    await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")
                elif default == "0":
                    await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} BOOLEAN NOT NULL DEFAULT 0")
                else:
                    await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
                await db.commit()
            except Exception:
                pass  # Column already exists

        # Migrate: add summary column to messages
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN summary TEXT")
            await db.commit()
        except Exception:
            pass  # Column already exists

        # Migrate: add images column to messages (JSON-encoded list of base64 strings)
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN images TEXT")
            await db.commit()
        except Exception:
            pass  # Column already exists

        # Fix any messages left in 'streaming' status from a previous crash
        await db.execute(
            "UPDATE messages SET status = 'incomplete' WHERE status = 'streaming'"
        )
        await db.commit()

    logger.info("SQLite database initialized at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _connect_db():
    """Open a connection with PRAGMA foreign_keys=ON."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        yield db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _compress_image_to_thumbnail(b64_str: str) -> str:
    raw_b64 = b64_str.split(",", 1)[-1] if "," in b64_str else b64_str
    if _HAS_PILLOW:
        try:
            data = base64.b64decode(raw_b64)
            img = Image.open(io.BytesIO(data))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            if img.width > _MAX_THUMBNAIL_WIDTH:
                ratio = _MAX_THUMBNAIL_WIDTH / img.width
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=_MAX_THUMBNAIL_QUALITY)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            logger.warning("Pillow thumbnail failed, falling back to truncation", exc_info=True)
    if len(raw_b64) > _FALLBACK_MAX_BYTES:
        raw_b64 = raw_b64[:_FALLBACK_MAX_BYTES]
    prefix = ""
    if "," in b64_str:
        prefix = b64_str.split(",", 1)[0] + ","
    return prefix + raw_b64


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
    provider_id: str = "claude-code",
    model: Optional[str] = None,
) -> dict:
    now = _now()
    provider_session_id = _uuid()
    session = {
        "id": _uuid(),
        "title": title or "New Session",
        "claude_session_id": provider_session_id,
        "status": "active",
        "role": role,
        "project_name": project_name,
        "project_dir": project_dir,
        "provider_id": provider_id,
        "model": model,
        "provider_session_id": provider_session_id,
        "provider_initialized": False,
        "created_at": now,
        "updated_at": now,
    }
    async with _connect_db() as db:
        await db.execute(
            """INSERT INTO sessions (id, title, claude_session_id, status, role, project_name, project_dir,
               provider_id, model, provider_session_id, provider_initialized, created_at, updated_at)
               VALUES (:id, :title, :claude_session_id, :status, :role, :project_name, :project_dir,
               :provider_id, :model, :provider_session_id, :provider_initialized, :created_at, :updated_at)""",
            session,
        )
        await db.commit()
    return session


async def list_sessions(limit: int = 200) -> list[dict]:
    async with _connect_db() as db:
        db.row_factory = _row_to_dict  # type: ignore[assignment]
        cursor = await db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
    return rows  # type: ignore[return-value]


async def get_session(session_id: str) -> Optional[dict]:
    async with _connect_db() as db:
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
    async with _connect_db() as db:
        cursor = await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()
        return cursor.rowcount > 0


async def update_session(session_id: str, title: str) -> Optional[dict]:
    """Update the session title and updated_at timestamp. Returns updated session or None."""
    now = _now()
    async with _connect_db() as db:
        cursor = await db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, session_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None
    return await get_session(session_id)


async def touch_session(session_id: str) -> None:
    """Update the updated_at timestamp."""
    async with _connect_db() as db:
        await db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        await db.commit()


async def mark_claude_initialized(session_id: str) -> None:
    """Mark that this session has been used with --session-id (first CLI call done)."""
    async with _connect_db() as db:
        await db.execute(
            "UPDATE sessions SET claude_initialized = 1 WHERE id = ?",
            (session_id,),
        )
        await db.commit()


async def mark_provider_initialized(session_id: str) -> None:
    """Mark that this session's provider has been initialized (first call done)."""
    async with _connect_db() as db:
        await db.execute(
            "UPDATE sessions SET provider_initialized = 1, claude_initialized = 1 WHERE id = ?",
            (session_id,),
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
    status: str = "complete",
    images: Optional[list[str]] = None,
) -> dict:
    now = _now()
    thumbnails = None
    if images:
        thumbnails = [_compress_image_to_thumbnail(img) for img in images]
    images_json = json.dumps(thumbnails) if thumbnails else None
    db_msg = {
        "id": _uuid(),
        "session_id": session_id,
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
        "thinking": thinking,
        "is_complete": is_complete,
        "status": status,
        "images": images_json,
        "created_at": now,
    }
    async with _connect_db() as db:
        await db.execute(
            """INSERT INTO messages (id, session_id, role, content, tool_calls, thinking, is_complete, status, images, created_at)
               VALUES (:id, :session_id, :role, :content, :tool_calls, :thinking, :is_complete, :status, :images, :created_at)""",
            db_msg,
        )
        await db.commit()
    await touch_session(session_id)
    return {**db_msg, "images": thumbnails}


_ALLOWED_MESSAGE_FIELDS = frozenset({
    "content", "tool_calls", "thinking", "is_complete", "status", "summary"
})


async def update_message(message_id: str, **fields) -> None:
    """Update specific fields on a message."""
    if not fields:
        return
    invalid = set(fields) - _ALLOWED_MESSAGE_FIELDS
    if invalid:
        raise ValueError(f"Unknown message fields: {invalid}")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [message_id]
    async with _connect_db() as db:
        await db.execute(
            f"UPDATE messages SET {set_clause} WHERE id = ?",
            values,
        )
        await db.commit()


async def delete_message(message_id: str) -> None:
    """Delete a single message by ID."""
    async with _connect_db() as db:
        await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await db.commit()


async def list_messages(session_id: str, limit: int = 200, offset: int = 0) -> list[dict]:
    async with _connect_db() as db:
        db.row_factory = _row_to_dict  # type: ignore[assignment]
        cursor = await db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        )
        rows = await cursor.fetchall()
    # Deserialize tool_calls from JSON string to list
    for row in rows:
        if row.get("tool_calls") and isinstance(row["tool_calls"], str):
            try:
                row["tool_calls"] = json.loads(row["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                row["tool_calls"] = []
        if row.get("images") and isinstance(row["images"], str):
            try:
                row["images"] = json.loads(row["images"])
            except (json.JSONDecodeError, TypeError):
                row["images"] = None
    return rows  # type: ignore[return-value]


async def count_messages(session_id: str) -> int:
    """Return the total number of messages for a session."""
    async with _connect_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Hook Events
# ---------------------------------------------------------------------------

async def cleanup_old_hook_events(max_age_days: int = 7) -> int:
    """Delete hook events older than max_age_days. Returns count of deleted rows."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    async with _connect_db() as db:
        cursor = await db.execute(
            "DELETE FROM hook_events WHERE created_at < ?", (cutoff,)
        )
        await db.commit()
        deleted = cursor.rowcount
    if deleted > 0:
        logger.info("Cleaned up %d hook events older than %d days", deleted, max_age_days)
    return deleted


async def list_hook_events(
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return recent hook events with pagination. Returns (events, total_count)."""
    async with _connect_db() as db:
        # Wrap COUNT + SELECT in an explicit transaction so the total
        # is consistent with the returned rows (prevents a concurrent
        # INSERT between the two queries from causing a mismatch).
        await db.execute("BEGIN")

        # Get total count
        cursor = await db.execute("SELECT COUNT(*) FROM hook_events")
        row = await cursor.fetchone()
        total = row[0] if row else 0

        # Get paginated results
        db.row_factory = _row_to_dict  # type: ignore[assignment]
        cursor = await db.execute(
            "SELECT * FROM hook_events ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()

        await db.execute("COMMIT")

    # Deserialize payload from JSON string to dict
    for row in rows:
        if row.get("payload") and isinstance(row["payload"], str):
            try:
                row["payload"] = json.loads(row["payload"])
            except (json.JSONDecodeError, TypeError):
                row["payload"] = {}

    return rows, total  # type: ignore[return-value]


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
    async with _connect_db() as db:
        await db.execute(
            """INSERT INTO hook_events (id, session_id, event_type, tool_name, payload, created_at)
               VALUES (:id, :session_id, :event_type, :tool_name, :payload, :created_at)""",
            evt,
        )
        await db.commit()
    return evt
