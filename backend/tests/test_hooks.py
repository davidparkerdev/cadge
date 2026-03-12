"""Integration tests for hook event endpoints."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch, MagicMock

import httpx
import pytest

from tests.conftest import parse_sse_events


# All Claude Code hook event types (must match hooks/README.md)
ALL_EVENT_TYPES = [
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "TaskCompleted",
    "PreCompact",
]


# ---------------------------------------------------------------------------
# POST /api/hooks/event -- basic ingestion
# ---------------------------------------------------------------------------


async def test_post_hook_event(client: httpx.AsyncClient):
    """Posting a basic hook event should return 201 with an id."""
    resp = await client.post(
        "/api/hooks/event",
        json={
            "event_type": "tool_start",
            "session_id": "sess-abc",
            "tool_name": "Bash",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["status"] == "received"


async def test_post_hook_event_with_metadata(client: httpx.AsyncClient):
    """Hook events can contain arbitrary extra fields."""
    resp = await client.post(
        "/api/hooks/event",
        json={
            "event_type": "tool_end",
            "session_id": "sess-xyz",
            "tool_name": "Read",
            "file_path": "/tmp/test.py",
            "duration_ms": 42,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["status"] == "received"


# ---------------------------------------------------------------------------
# POST /api/hooks/event -- all Claude Code event types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
async def test_all_event_types_accepted(client: httpx.AsyncClient, event_type: str):
    """Every Claude Code hook event type should be accepted and return 201."""
    payload = {
        "event_type": event_type,
        "session_id": f"sess-{event_type.lower()}",
    }
    # Add tool_name for tool-related events
    if "Tool" in event_type:
        payload["tool_name"] = "Bash"
        payload["tool"] = {"name": "Bash"}

    resp = await client.post("/api/hooks/event", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["status"] == "received"


# ---------------------------------------------------------------------------
# POST /api/hooks/event -- DB persistence
# ---------------------------------------------------------------------------


async def test_hook_event_persisted_to_db(client: httpx.AsyncClient):
    """A posted hook event should be readable from the database."""
    resp = await client.post(
        "/api/hooks/event",
        json={
            "event_type": "PreToolUse",
            "session_id": "sess-persist",
            "tool_name": "Edit",
            "tool": {"name": "Edit"},
        },
    )
    assert resp.status_code == 201
    event_id = resp.json()["id"]

    # Read back from DB directly
    from app.services import session_store
    import aiosqlite

    async with aiosqlite.connect(str(session_store.DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM hook_events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row["id"] == event_id
    assert row["event_type"] == "PreToolUse"
    assert row["session_id"] == "sess-persist"
    assert row["tool_name"] == "Edit"
    assert row["created_at"] is not None

    # Payload should contain the full original JSON
    payload = json.loads(row["payload"])
    assert payload["event_type"] == "PreToolUse"
    assert payload["tool"]["name"] == "Edit"


async def test_multiple_events_persisted_independently(client: httpx.AsyncClient):
    """Multiple hook events should each get unique IDs and be stored independently."""
    ids = []
    for i in range(3):
        resp = await client.post(
            "/api/hooks/event",
            json={
                "event_type": "PostToolUse",
                "session_id": "sess-multi",
                "tool_name": f"Tool{i}",
            },
        )
        assert resp.status_code == 201
        ids.append(resp.json()["id"])

    # All IDs should be unique
    assert len(set(ids)) == 3

    # Verify all are in DB
    from app.services import session_store
    import aiosqlite

    async with aiosqlite.connect(str(session_store.DB_PATH)) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM hook_events WHERE session_id = ?",
            ("sess-multi",),
        )
        row = await cursor.fetchone()
        assert row[0] == 3


# ---------------------------------------------------------------------------
# POST /api/hooks/event -- SSE broadcast via hooks_broker
# ---------------------------------------------------------------------------


async def test_hook_event_broadcast_to_sse(client: httpx.AsyncClient):
    """A posted hook event should be broadcast through the hooks SSE broker."""
    from app.services.stream_broker import hooks_broker, HOOKS_GLOBAL_KEY

    received: list[dict] = []

    async def reader():
        async for event in hooks_broker.subscribe(HOOKS_GLOBAL_KEY):
            received.append(event)

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.02)  # let subscriber register

    resp = await client.post(
        "/api/hooks/event",
        json={
            "event_type": "UserPromptSubmit",
            "session_id": "sess-broadcast",
            "tool_name": None,
        },
    )
    assert resp.status_code == 201
    event_id = resp.json()["id"]

    await asyncio.sleep(0.02)  # let event propagate

    hooks_broker.close_session(HOOKS_GLOBAL_KEY)
    await asyncio.sleep(0.02)
    await task

    assert len(received) >= 1
    broadcast = received[0]
    assert broadcast["id"] == event_id
    assert broadcast["event_type"] == "UserPromptSubmit"
    assert broadcast["session_id"] == "sess-broadcast"


# ---------------------------------------------------------------------------
# GET /api/hooks/stream  (SSE)
# ---------------------------------------------------------------------------


async def test_hook_stream_connects(client: httpx.AsyncClient):
    """Connecting to the hooks SSE stream should yield a 'connected' event."""
    async with client.stream("GET", "/api/hooks/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        first_chunk = b""
        async for chunk in resp.aiter_bytes():
            first_chunk += chunk
            if b"\n\n" in first_chunk:
                break

    events = parse_sse_events(first_chunk.decode())
    assert len(events) >= 1
    assert events[0]["type"] == "connected"


async def test_hook_stream_receives_posted_events(client: httpx.AsyncClient):
    """Events POSTed to /api/hooks/event should appear on the SSE stream."""
    collected = b""

    async def post_event():
        # Wait for stream to connect first
        await asyncio.sleep(0.1)
        await client.post(
            "/api/hooks/event",
            json={
                "event_type": "SessionStart",
                "session_id": "sess-sse-test",
            },
        )

    post_task = asyncio.create_task(post_event())

    async with client.stream("GET", "/api/hooks/stream") as resp:
        assert resp.status_code == 200
        async for chunk in resp.aiter_bytes():
            collected += chunk
            # Wait until we have at least the connected event + one real event
            events = parse_sse_events(collected.decode())
            if len(events) >= 2:
                break

    await post_task

    events = parse_sse_events(collected.decode())
    assert events[0]["type"] == "connected"
    assert any(e.get("event_type") == "SessionStart" for e in events)
    session_event = next(e for e in events if e.get("event_type") == "SessionStart")
    assert session_event["session_id"] == "sess-sse-test"


# ---------------------------------------------------------------------------
# POST /api/hooks/event -- robustness (malformed/missing fields)
# ---------------------------------------------------------------------------


async def test_hook_event_missing_event_type(client: httpx.AsyncClient):
    """An event with no event_type should still be accepted (field is optional)."""
    resp = await client.post(
        "/api/hooks/event",
        json={"session_id": "sess-no-type"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data


async def test_hook_event_missing_session_id(client: httpx.AsyncClient):
    """An event with no session_id should still be accepted."""
    resp = await client.post(
        "/api/hooks/event",
        json={"event_type": "Stop"},
    )
    assert resp.status_code == 201


async def test_hook_event_missing_tool_name(client: httpx.AsyncClient):
    """An event with no tool_name should still be accepted."""
    resp = await client.post(
        "/api/hooks/event",
        json={"event_type": "Notification", "session_id": "sess-no-tool"},
    )
    assert resp.status_code == 201


async def test_hook_event_empty_payload(client: httpx.AsyncClient):
    """An empty JSON payload should still be accepted."""
    resp = await client.post("/api/hooks/event", json={})
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data


async def test_hook_event_type_from_type_field(client: httpx.AsyncClient):
    """The endpoint should also accept 'type' as an alias for 'event_type'."""
    resp = await client.post(
        "/api/hooks/event",
        json={"type": "PreCompact", "session_id": "sess-alias"},
    )
    assert resp.status_code == 201

    # Verify it was stored with the correct event_type
    event_id = resp.json()["id"]
    from app.services import session_store
    import aiosqlite

    async with aiosqlite.connect(str(session_store.DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT event_type FROM hook_events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()

    assert row["event_type"] == "PreCompact"


async def test_hook_event_tool_name_from_nested_tool(client: httpx.AsyncClient):
    """The endpoint should extract tool_name from nested tool.name if top-level is missing."""
    resp = await client.post(
        "/api/hooks/event",
        json={
            "event_type": "PreToolUse",
            "session_id": "sess-nested",
            "tool": {"name": "Grep", "params": {"pattern": "test"}},
        },
    )
    assert resp.status_code == 201

    event_id = resp.json()["id"]
    from app.services import session_store
    import aiosqlite

    async with aiosqlite.connect(str(session_store.DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT tool_name FROM hook_events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()

    assert row["tool_name"] == "Grep"


async def test_hook_event_extra_fields_preserved_in_payload(client: httpx.AsyncClient):
    """Arbitrary extra fields in the hook event should be preserved in the stored payload."""
    resp = await client.post(
        "/api/hooks/event",
        json={
            "event_type": "PostToolUse",
            "session_id": "sess-extra",
            "tool_name": "Bash",
            "custom_field": "custom_value",
            "nested": {"deep": True},
        },
    )
    assert resp.status_code == 201

    event_id = resp.json()["id"]
    from app.services import session_store
    import aiosqlite

    async with aiosqlite.connect(str(session_store.DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT payload FROM hook_events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()

    payload = json.loads(row["payload"])
    assert payload["custom_field"] == "custom_value"
    assert payload["nested"]["deep"] is True


# ---------------------------------------------------------------------------
# Observatory push integration
# ---------------------------------------------------------------------------


async def test_observatory_push_called_on_hook_event(client: httpx.AsyncClient):
    """Each hook event should trigger a fire-and-forget push to Observatory."""
    with patch("app.routes.hooks.push_hook_event") as mock_push:
        resp = await client.post(
            "/api/hooks/event",
            json={
                "event_type": "PreToolUse",
                "session_id": "sess-obs",
                "tool_name": "Bash",
                "tool": {"name": "Bash"},
            },
        )
        assert resp.status_code == 201

        mock_push.assert_called_once_with(
            event_type="PreToolUse",
            session_id="sess-obs",
            tool_name="Bash",
            payload={
                "event_type": "PreToolUse",
                "session_id": "sess-obs",
                "tool_name": "Bash",
                "tool": {"name": "Bash"},
            },
        )


@pytest.mark.parametrize("event_type", ["SessionStart", "Stop", "Notification"])
async def test_observatory_push_for_various_events(
    client: httpx.AsyncClient, event_type: str
):
    """Observatory push should be called for every event type, not just tool events."""
    with patch("app.routes.hooks.push_hook_event") as mock_push:
        resp = await client.post(
            "/api/hooks/event",
            json={"event_type": event_type, "session_id": "sess-obs-multi"},
        )
        assert resp.status_code == 201
        mock_push.assert_called_once()
        call_kwargs = mock_push.call_args
        assert call_kwargs.kwargs["event_type"] == event_type
        assert call_kwargs.kwargs["session_id"] == "sess-obs-multi"


async def test_observatory_push_with_no_event_type(client: httpx.AsyncClient):
    """Observatory push should still be called even when event_type is None."""
    with patch("app.routes.hooks.push_hook_event") as mock_push:
        resp = await client.post(
            "/api/hooks/event",
            json={"session_id": "sess-obs-none"},
        )
        assert resp.status_code == 201
        mock_push.assert_called_once()
        call_kwargs = mock_push.call_args
        assert call_kwargs.kwargs["event_type"] is None
