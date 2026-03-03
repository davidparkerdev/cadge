"""Integration tests for hook event endpoints."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import parse_sse_events


# ---------------------------------------------------------------------------
# POST /api/hooks/event
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
