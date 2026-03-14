"""Tests for the event store module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import aiosqlite
import pytest

from app.services import event_store, session_store
from app.services.event_store import (
    CONTENT_DELTA,
    STREAM_END,
    STREAM_START,
    TOOL_END,
    TOOL_START,
    append_event,
    cleanup_old_events,
    delete_session_events,
    event_stream,
    get_events,
    get_latest_seq,
    init_events_table,
    wait_for_events,
)


# ---------------------------------------------------------------------------
# Fixture: per-test isolated SQLite database
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _db(tmp_path):
    """Create a fresh SQLite database for each test and patch DB_PATH."""
    db_path = str(tmp_path / "test_events.db")

    with patch.object(session_store, "DB_PATH", db_path), \
         patch.object(event_store, "DB_PATH", db_path):
        await init_events_table()
        # Clear any leftover conditions and deleted sessions from previous tests
        event_store._session_conditions.clear()
        event_store._deleted_sessions.clear()
        yield db_path


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


async def test_init_creates_table(_db):
    """init_events_table creates the events table."""
    async with aiosqlite.connect(_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        )
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "events"


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------


async def test_append_event_returns_seq(_db):
    """Appending events returns incrementing sequence numbers."""
    seq1 = await append_event("sess-1", STREAM_START)
    seq2 = await append_event("sess-1", CONTENT_DELTA, {"text": "hello"})
    seq3 = await append_event("sess-1", STREAM_END)

    assert seq1 == 1
    assert seq2 == 2
    assert seq3 == 3


async def test_append_event_per_session_seq(_db):
    """Two sessions have independent sequence counters."""
    seq_a1 = await append_event("sess-a", STREAM_START)
    seq_b1 = await append_event("sess-b", STREAM_START)
    seq_a2 = await append_event("sess-a", CONTENT_DELTA)
    seq_b2 = await append_event("sess-b", CONTENT_DELTA)

    assert seq_a1 == 1
    assert seq_a2 == 2
    assert seq_b1 == 1
    assert seq_b2 == 2


# ---------------------------------------------------------------------------
# get_events
# ---------------------------------------------------------------------------


async def test_get_events_since_seq(_db):
    """get_events only returns events after the given seq."""
    await append_event("sess-1", STREAM_START)
    await append_event("sess-1", CONTENT_DELTA, {"text": "a"})
    await append_event("sess-1", CONTENT_DELTA, {"text": "b"})
    await append_event("sess-1", STREAM_END)

    events = await get_events("sess-1", since_seq=2)
    assert len(events) == 2
    assert events[0]["seq"] == 3
    assert events[1]["seq"] == 4
    assert events[1]["event_type"] == STREAM_END


async def test_get_events_empty_session(_db):
    """get_events returns empty list for unknown session."""
    events = await get_events("nonexistent")
    assert events == []


# ---------------------------------------------------------------------------
# get_latest_seq
# ---------------------------------------------------------------------------


async def test_get_latest_seq(_db):
    """get_latest_seq returns the highest seq for a session."""
    await append_event("sess-1", STREAM_START)
    await append_event("sess-1", CONTENT_DELTA)
    await append_event("sess-1", STREAM_END)

    latest = await get_latest_seq("sess-1")
    assert latest == 3


async def test_get_latest_seq_empty(_db):
    """get_latest_seq returns 0 for unknown session."""
    latest = await get_latest_seq("nonexistent")
    assert latest == 0


# ---------------------------------------------------------------------------
# delete_session_events
# ---------------------------------------------------------------------------


async def test_delete_session_events(_db):
    """delete_session_events deletes all events for a session."""
    await append_event("sess-1", STREAM_START)
    await append_event("sess-1", CONTENT_DELTA)
    await append_event("sess-2", STREAM_START)

    deleted = await delete_session_events("sess-1")
    assert deleted == 2

    # sess-1 events should be gone
    events = await get_events("sess-1")
    assert events == []

    # sess-2 events should remain
    events = await get_events("sess-2")
    assert len(events) == 1


# ---------------------------------------------------------------------------
# cleanup_old_events
# ---------------------------------------------------------------------------


async def test_cleanup_old_events(_db):
    """cleanup_old_events deletes events older than max_age_days."""
    # Insert an event with an old timestamp directly
    old_time = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    async with aiosqlite.connect(_db) as db:
        await db.execute(
            """INSERT INTO events (session_id, seq, event_type, data, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("old-sess", 1, STREAM_START, "{}", old_time),
        )
        await db.commit()

    # Insert a recent event
    await append_event("new-sess", STREAM_START)

    deleted = await cleanup_old_events(max_age_days=30)
    assert deleted == 1

    # Old event should be gone
    events = await get_events("old-sess")
    assert events == []

    # New event should remain
    events = await get_events("new-sess")
    assert len(events) == 1


# ---------------------------------------------------------------------------
# wait_for_events / notification
# ---------------------------------------------------------------------------


async def test_wait_for_events_timeout(_db):
    """wait_for_events returns False on timeout."""
    result = await wait_for_events("sess-1", timeout=0.05)
    assert result is False


async def test_wait_for_events_notified(_db):
    """wait_for_events returns True when notified by append_event."""
    notified = None

    async def waiter():
        nonlocal notified
        notified = await wait_for_events("sess-1", timeout=2.0)

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)

    # Append an event, which should notify the waiter
    await append_event("sess-1", STREAM_START)
    await task

    assert notified is True


# ---------------------------------------------------------------------------
# event_stream
# ---------------------------------------------------------------------------


async def test_event_stream_catchup(_db):
    """event_stream yields existing events first (catch-up phase)."""
    await append_event("sess-1", STREAM_START)
    await append_event("sess-1", CONTENT_DELTA, {"text": "hello"})
    await append_event("sess-1", STREAM_END)

    received: list[dict] = []
    stream = event_stream("sess-1", since_seq=0)

    # Collect the catch-up events then cancel
    try:
        async with asyncio.timeout(0.5):
            async for event in stream:
                received.append(event)
                if len(received) >= 3:
                    break
    except asyncio.TimeoutError:
        pass

    assert len(received) == 3
    assert received[0]["event_type"] == STREAM_START
    assert received[1]["event_type"] == CONTENT_DELTA
    assert received[1]["data"] == {"text": "hello"}
    assert received[2]["event_type"] == STREAM_END


async def test_event_stream_live(_db):
    """event_stream waits then yields new events appended concurrently."""
    received: list[dict] = []

    async def reader():
        async for event in event_stream("sess-1", since_seq=0):
            received.append(event)
            if len(received) >= 2:
                break

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.05)

    # No events yet -- reader should be waiting
    assert len(received) == 0

    # Append events concurrently
    await append_event("sess-1", TOOL_START, {"tool": "Read"})
    await append_event("sess-1", TOOL_END, {"tool": "Read"})

    # Wait for reader to pick them up
    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 2
    assert received[0]["event_type"] == TOOL_START
    assert received[0]["data"] == {"tool": "Read"}
    assert received[1]["event_type"] == TOOL_END


# ---------------------------------------------------------------------------
# JSON roundtrip
# ---------------------------------------------------------------------------


async def test_data_json_roundtrip(_db):
    """data dict survives JSON serialization/deserialization."""
    complex_data = {
        "text": "hello world",
        "count": 42,
        "nested": {"key": "value", "list": [1, 2, 3]},
        "flag": True,
        "empty": None,
    }

    await append_event("sess-1", CONTENT_DELTA, complex_data)
    events = await get_events("sess-1")

    assert len(events) == 1
    assert events[0]["data"] == complex_data
