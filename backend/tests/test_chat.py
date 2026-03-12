"""Integration tests for chat endpoints (messages, answers, SSE)."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import create_test_session, parse_sse_events


# ---------------------------------------------------------------------------
# POST /api/sessions/{id}/messages
# ---------------------------------------------------------------------------


async def test_send_message_returns_202(client: httpx.AsyncClient):
    """Sending a message to a valid session should return 202 with a messageId."""
    session = await create_test_session(client)

    resp = await client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "Hello, Claude!"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "messageId" in data
    assert data["status"] == "streaming"


async def test_send_message_session_not_found(client: httpx.AsyncClient):
    """Sending a message to a non-existent session should return 404."""
    resp = await client.post(
        "/api/sessions/nonexistent-id/messages",
        json={"content": "Hello"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/sessions/{id}/messages
# ---------------------------------------------------------------------------


async def test_get_messages_empty(client: httpx.AsyncClient):
    """A freshly created session should have no messages."""
    session = await create_test_session(client)

    resp = await client.get(f"/api/sessions/{session['id']}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_messages_returns_sent(client: httpx.AsyncClient):
    """After sending a message, the user message should appear in the list."""
    session = await create_test_session(client)

    await client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "Test message content"},
    )

    resp = await client.get(f"/api/sessions/{session['id']}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Test message content"
    assert messages[0]["is_complete"] is True


async def test_get_messages_pagination_headers(client: httpx.AsyncClient):
    """GET messages should include X-Total-Count, X-Limit, X-Offset headers."""
    session = await create_test_session(client)

    # Create 5 messages
    for i in range(5):
        await client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": f"Message {i}"},
        )

    resp = await client.get(
        f"/api/sessions/{session['id']}/messages",
        params={"limit": 2, "offset": 0},
    )
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2
    assert resp.headers["X-Total-Count"] == "5"
    assert resp.headers["X-Limit"] == "2"
    assert resp.headers["X-Offset"] == "0"
    # Should return the first two messages
    assert messages[0]["content"] == "Message 0"
    assert messages[1]["content"] == "Message 1"


async def test_get_messages_pagination_offset(client: httpx.AsyncClient):
    """Offset should skip messages correctly."""
    session = await create_test_session(client)

    for i in range(5):
        await client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": f"Message {i}"},
        )

    resp = await client.get(
        f"/api/sessions/{session['id']}/messages",
        params={"limit": 2, "offset": 2},
    )
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2
    assert resp.headers["X-Total-Count"] == "5"
    assert resp.headers["X-Offset"] == "2"
    assert messages[0]["content"] == "Message 2"
    assert messages[1]["content"] == "Message 3"


async def test_get_messages_default_no_params(client: httpx.AsyncClient):
    """Without params, all messages should be returned (up to default limit)."""
    session = await create_test_session(client)

    for i in range(3):
        await client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": f"Message {i}"},
        )

    resp = await client.get(f"/api/sessions/{session['id']}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 3
    assert resp.headers["X-Total-Count"] == "3"
    assert resp.headers["X-Limit"] == "200"
    assert resp.headers["X-Offset"] == "0"


# ---------------------------------------------------------------------------
# POST /api/sessions/{id}/answer
# ---------------------------------------------------------------------------


async def test_answer_question_returns_202(client: httpx.AsyncClient):
    """Answering a question should return 202 and persist a user message."""
    session = await create_test_session(client)

    resp = await client.post(
        f"/api/sessions/{session['id']}/answer",
        json={
            "answer": "Yes, proceed",
            "questionText": "Should I continue?",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "messageId" in data
    assert data["status"] == "streaming"

    # Verify the message was persisted
    resp = await client.get(f"/api/sessions/{session['id']}/messages")
    messages = resp.json()
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "Yes, proceed" in messages[0]["content"]
    assert "Should I continue?" in messages[0]["content"]


# ---------------------------------------------------------------------------
# GET /api/sessions/{id}/stream  (SSE)
# ---------------------------------------------------------------------------


async def test_sse_stream_connects(client: httpx.AsyncClient):
    """Connecting to the SSE stream should yield an initial 'connected' event."""
    session = await create_test_session(client)

    async with client.stream(
        "GET", f"/api/sessions/{session['id']}/stream"
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        # Read just the first SSE chunk
        first_chunk = b""
        async for chunk in resp.aiter_bytes():
            first_chunk += chunk
            # Once we have a complete SSE event (ends with \n\n), stop
            if b"\n\n" in first_chunk:
                break

    events = parse_sse_events(first_chunk.decode())
    assert len(events) >= 1
    assert events[0]["type"] == "connected"
    assert events[0]["session_id"] == session["id"]
    assert events[0]["streaming"] is False
