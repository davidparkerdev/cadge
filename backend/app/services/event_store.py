"""Persistent event store for streaming events.

Stores all streaming events in SQLite with per-session sequence numbers
and provides an asyncio notification mechanism for real-time SSE delivery.
Uses the same database as session_store (nexus_v2.db).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import aiosqlite

from app.services.session_store import DB_PATH, _connect_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

# Stream lifecycle
STREAM_START = "stream_start"
STREAM_END = "stream_end"
STREAM_ERROR = "stream_error"
STREAM_CANCELLED = "stream_cancelled"

# Content
CONTENT_DELTA = "content_delta"
THINKING_DELTA = "thinking_delta"

# Tools
TOOL_START = "tool_start"
TOOL_END = "tool_end"

# Agents (sub-agents spawned by Task tool)
AGENT_SPAWN = "agent_spawn"
AGENT_COMPLETE = "agent_complete"

# Raw/passthrough events from Claude CLI
RAW_EVENT = "raw_event"

# ---------------------------------------------------------------------------
# Per-session notification conditions
# ---------------------------------------------------------------------------

_session_conditions: dict[str, asyncio.Condition] = {}

# Track sessions whose events have been deleted so SSE waiters can
# detect the deletion and exit gracefully instead of hanging.
_deleted_sessions: set[str] = set()


def _get_condition(session_id: str) -> asyncio.Condition:
    """Get or create an asyncio.Condition for a session."""
    if session_id not in _session_conditions:
        _session_conditions[session_id] = asyncio.Condition()
    return _session_conditions[session_id]


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

_CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq);
"""


async def init_events_table() -> None:
    """Create the events table if it doesn't exist. Call from app lifespan."""
    async with _connect_db() as db:
        await db.executescript(_CREATE_EVENTS_TABLE)
        await db.commit()
    logger.info("Events table initialized")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

async def append_event(session_id: str, event_type: str, data: dict | None = None) -> int:
    """Append an event to the session's event log. Returns the sequence number.

    Sequence numbers are per-session, auto-incrementing starting from 1.
    After inserting, notifies any waiters via the per-session asyncio.Condition.
    """
    now = _now()
    data_json = json.dumps(data or {})

    async with _connect_db() as db:
        cursor = await db.execute(
            """INSERT INTO events (session_id, seq, event_type, data, created_at)
               VALUES (?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE session_id = ?), ?, ?, ?)
               RETURNING seq""",
            (session_id, session_id, event_type, data_json, now),
        )
        row = await cursor.fetchone()
        await db.commit()
        seq = row[0]

    await _notify_new_event(session_id)
    return seq


async def get_events(session_id: str, since_seq: int = 0, limit: int = 5000) -> list[dict]:
    """Get events for a session where seq > since_seq, ordered by seq ASC.

    Returns list of dicts: {seq, event_type, data (parsed JSON), created_at}
    """
    async with _connect_db() as db:
        cursor = await db.execute(
            """SELECT seq, event_type, data, created_at
               FROM events
               WHERE session_id = ? AND seq > ?
               ORDER BY seq ASC
               LIMIT ?""",
            (session_id, since_seq, limit),
        )
        rows = await cursor.fetchall()

    result = []
    for row in rows:
        seq, event_type, data_str, created_at = row
        try:
            data = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            data = {}
        result.append({
            "seq": seq,
            "event_type": event_type,
            "data": data,
            "created_at": created_at,
        })
    return result


async def get_latest_seq(session_id: str) -> int:
    """Get the latest sequence number for a session. Returns 0 if no events."""
    async with _connect_db() as db:
        cursor = await db.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM events WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def wait_for_events(session_id: str, timeout: float = 30.0) -> bool:
    """Wait until new events are available for this session.

    Uses an asyncio.Condition per session. Returns True if notified
    (new events available), False on timeout.
    """
    condition = _get_condition(session_id)
    try:
        async with condition:
            result = await asyncio.wait_for(condition.wait(), timeout=timeout)
            return result
    except asyncio.TimeoutError:
        return False


async def _notify_new_event(session_id: str) -> None:
    """Notify all waiters that a new event is available for this session."""
    condition = _get_condition(session_id)
    async with condition:
        condition.notify_all()


async def delete_session_events(session_id: str) -> int:
    """Delete all events for a session and clean up its condition. Returns count of deleted rows."""
    async with _connect_db() as db:
        cursor = await db.execute(
            "DELETE FROM events WHERE session_id = ?",
            (session_id,),
        )
        await db.commit()
        deleted = cursor.rowcount
    # Track that this session's events have been deleted so SSE waiters
    # can detect the deletion and exit gracefully.
    _deleted_sessions.add(session_id)
    # Notify any waiters on the old Condition so they wake up and see
    # the session is gone, rather than hanging for up to 30 minutes.
    condition = _session_conditions.get(session_id)
    if condition:
        async with condition:
            condition.notify_all()
    # Clean up the per-session condition to prevent memory leak
    _session_conditions.pop(session_id, None)
    return deleted


async def cleanup_old_events(max_age_days: int = 30) -> int:
    """Delete events older than max_age_days. Returns count deleted.

    Also cleans up _session_conditions for sessions that no longer have
    any events in the DB, preventing unbounded memory growth.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    async with _connect_db() as db:
        cursor = await db.execute(
            "DELETE FROM events WHERE created_at < ?",
            (cutoff,),
        )
        await db.commit()
        deleted = cursor.rowcount

        if deleted > 0:
            # Find sessions that still have events in the DB
            cursor = await db.execute("SELECT DISTINCT session_id FROM events")
            active_sessions = {row[0] for row in await cursor.fetchall()}

    # Remove in-memory conditions for sessions no longer in the events table
    if deleted > 0:
        stale = [sid for sid in _session_conditions if sid not in active_sessions]
        for sid in stale:
            _session_conditions.pop(sid, None)
        if stale:
            logger.info("Cleaned up %d stale session conditions", len(stale))
        # Also clean up _deleted_sessions entries for sessions that no longer
        # have any events -- they've served their purpose of waking SSE waiters.
        stale_deleted = _deleted_sessions - active_sessions
        _deleted_sessions.difference_update(stale_deleted)
        logger.info("Cleaned up %d events older than %d days", deleted, max_age_days)
    return deleted


_TERMINAL_EVENT_TYPES = frozenset({STREAM_END, STREAM_ERROR, STREAM_CANCELLED})


async def event_stream(session_id: str, since_seq: int = 0) -> AsyncGenerator[dict, None]:
    """Async generator that yields events for a session, starting from since_seq.

    First yields all existing events from DB where seq > since_seq (catch-up).
    Then enters a loop: wait_for_events(), query new events, yield them.
    Terminates after yielding a terminal event during the LIVE phase only.
    Historical terminal events during catch-up are yielded but do NOT terminate
    the generator -- this prevents rapid reconnect storms when opening sessions
    with multiple completed messages.

    Yields dicts: {seq, event_type, data, created_at}
    """
    last_seq = since_seq

    # Phase 1: catch-up -- yield all existing events after since_seq.
    # Do NOT terminate on terminal events here -- they're historical.
    events = await get_events(session_id, since_seq=last_seq)
    for event in events:
        yield event
        last_seq = event["seq"]

    # Phase 2: live -- wait for new events and yield them
    # Cap idle iterations to prevent infinite loops if no events ever arrive
    # (e.g., session was deleted, or claude process never started).
    idle_cycles = 0
    max_idle_cycles = 60  # 60 * 30s timeout = 30 min max idle
    while True:
        # Check if the session's events were deleted while we were waiting
        if session_id in _deleted_sessions:
            logger.info(
                "event_stream for session %s exiting: session events deleted",
                session_id,
            )
            return
        notified = await wait_for_events(session_id, timeout=30.0)
        if notified:
            # Re-check after waking up -- the notification may have been
            # from delete_session_events() rather than a new event.
            if session_id in _deleted_sessions:
                logger.info(
                    "event_stream for session %s exiting: session events deleted",
                    session_id,
                )
                return
            idle_cycles = 0
            events = await get_events(session_id, since_seq=last_seq)
            for event in events:
                yield event
                last_seq = event["seq"]
                if event["event_type"] in _TERMINAL_EVENT_TYPES:
                    return
        else:
            idle_cycles += 1
            if idle_cycles >= max_idle_cycles:
                logger.warning(
                    "event_stream for session %s idle for %d cycles, terminating",
                    session_id, idle_cycles,
                )
                return
