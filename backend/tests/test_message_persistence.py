"""Tests for message persistence: status tracking, periodic saves, crash recovery.

These tests verify that messages survive interrupted streams, crashes, and
app restarts -- the core reliability guarantees of Cadge.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from tests.conftest import create_test_session


# ---------------------------------------------------------------------------
# Message status tracking
# ---------------------------------------------------------------------------


async def test_user_message_has_complete_status(client: httpx.AsyncClient):
    """User messages should always have status='complete'."""
    session = await create_test_session(client)

    await client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "Hello"},
    )

    resp = await client.get(f"/api/sessions/{session['id']}/messages")
    messages = resp.json()
    assert len(messages) == 1
    assert messages[0]["status"] == "complete"
    assert messages[0]["role"] == "user"
    assert messages[0]["is_complete"] is True


async def test_message_response_includes_status_field(client: httpx.AsyncClient):
    """The API should always return the status field in message responses."""
    session = await create_test_session(client)

    await client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "Test"},
    )

    resp = await client.get(f"/api/sessions/{session['id']}/messages")
    messages = resp.json()
    assert len(messages) >= 1
    for msg in messages:
        assert "status" in msg, f"Message {msg['id']} missing 'status' field"
        assert msg["status"] in ("complete", "streaming", "incomplete", "error")


# ---------------------------------------------------------------------------
# Direct session_store tests (no HTTP layer)
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path):
    """Yield a configured session_store module with a temp database."""
    db_path = str(tmp_path / "persist_test.db")
    with patch("app.services.session_store.DB_PATH", db_path):
        from app.services.session_store import (
            create_message,
            create_session,
            delete_message,
            init_db,
            list_messages,
            update_message,
        )

        await init_db()
        yield {
            "create_session": create_session,
            "create_message": create_message,
            "update_message": update_message,
            "delete_message": delete_message,
            "list_messages": list_messages,
        }


async def test_create_streaming_placeholder(store):
    """Creating a message with status='streaming' should persist it."""
    session = await store["create_session"](title="Test")

    msg = await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="",
        is_complete=False,
        status="streaming",
    )

    messages = await store["list_messages"](session["id"])
    assert len(messages) == 1
    assert messages[0]["id"] == msg["id"]
    assert messages[0]["status"] == "streaming"
    assert messages[0]["content"] == ""
    assert messages[0]["is_complete"] == 0  # SQLite boolean


async def test_update_streaming_to_complete(store):
    """A streaming placeholder should be updatable to complete with content."""
    session = await store["create_session"](title="Test")

    msg = await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="",
        is_complete=False,
        status="streaming",
    )

    await store["update_message"](
        msg["id"],
        content="Hello! I'm Claude.",
        is_complete=True,
        status="complete",
    )

    messages = await store["list_messages"](session["id"])
    assert len(messages) == 1
    assert messages[0]["content"] == "Hello! I'm Claude."
    assert messages[0]["status"] == "complete"
    assert messages[0]["is_complete"] == 1


async def test_periodic_save_updates_content(store):
    """Periodic saves should update content without changing status."""
    session = await store["create_session"](title="Test")

    msg = await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="",
        is_complete=False,
        status="streaming",
    )

    # Simulate periodic save (partial content)
    await store["update_message"](
        msg["id"],
        content="Partial response so far...",
    )

    messages = await store["list_messages"](session["id"])
    assert len(messages) == 1
    assert messages[0]["content"] == "Partial response so far..."
    assert messages[0]["status"] == "streaming"  # Still streaming

    # Simulate another periodic save with more content
    await store["update_message"](
        msg["id"],
        content="Partial response so far... and more text here.",
    )

    messages = await store["list_messages"](session["id"])
    assert messages[0]["content"] == "Partial response so far... and more text here."


async def test_crash_recovery_marks_streaming_as_incomplete(store):
    """On init_db, messages stuck in 'streaming' should become 'incomplete'."""
    session = await store["create_session"](title="Test")

    # Create a message in streaming state (simulating a crash mid-stream)
    msg = await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="Partial content from before crash",
        is_complete=False,
        status="streaming",
    )

    # Re-init the DB (simulates server restart)
    from app.services.session_store import init_db

    await init_db()

    # The streaming message should now be marked as incomplete
    messages = await store["list_messages"](session["id"])
    assert len(messages) == 1
    assert messages[0]["id"] == msg["id"]
    assert messages[0]["status"] == "incomplete"
    assert messages[0]["content"] == "Partial content from before crash"


async def test_delete_empty_placeholder(store):
    """An empty placeholder (no content, no error) should be deletable."""
    session = await store["create_session"](title="Test")

    msg = await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="",
        is_complete=False,
        status="streaming",
    )

    await store["delete_message"](msg["id"])

    messages = await store["list_messages"](session["id"])
    assert len(messages) == 0


async def test_error_status_preserves_partial_content(store):
    """When claude errors, partial content should be preserved with error status."""
    session = await store["create_session"](title="Test")

    msg = await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="",
        is_complete=False,
        status="streaming",
    )

    # Simulate error with partial content
    await store["update_message"](
        msg["id"],
        content="Here's what I was saying before the error...",
        is_complete=True,
        status="error",
    )

    messages = await store["list_messages"](session["id"])
    assert len(messages) == 1
    assert messages[0]["status"] == "error"
    assert messages[0]["content"] == "Here's what I was saying before the error..."
    assert messages[0]["is_complete"] == 1


async def test_tool_calls_persist_with_message(store):
    """Tool calls should be persisted as JSON and deserialized on read."""
    session = await store["create_session"](title="Test")

    tool_calls = [
        {"name": "Read", "input": {"path": "/tmp/file"}, "status": "completed"}
    ]

    msg = await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="Let me read that file.",
        tool_calls=json.dumps(tool_calls),
        is_complete=True,
        status="complete",
    )

    messages = await store["list_messages"](session["id"])
    assert len(messages) == 1
    # list_messages deserializes tool_calls from JSON
    assert messages[0]["tool_calls"] == tool_calls


async def test_thinking_persists_with_message(store):
    """Thinking content should persist alongside the message."""
    session = await store["create_session"](title="Test")

    await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="The answer is 42.",
        thinking="Let me think about this... The user is asking about...",
        is_complete=True,
        status="complete",
    )

    messages = await store["list_messages"](session["id"])
    assert len(messages) == 1
    assert messages[0]["thinking"] == "Let me think about this... The user is asking about..."


# ---------------------------------------------------------------------------
# Multiple messages in a conversation
# ---------------------------------------------------------------------------


async def test_conversation_preserves_order(store):
    """Messages should be returned in chronological order."""
    session = await store["create_session"](title="Test")

    await store["create_message"](
        session_id=session["id"],
        role="user",
        content="First message",
        is_complete=True,
    )

    await store["create_message"](
        session_id=session["id"],
        role="assistant",
        content="First response",
        is_complete=True,
    )

    await store["create_message"](
        session_id=session["id"],
        role="user",
        content="Second message",
        is_complete=True,
    )

    messages = await store["list_messages"](session["id"])
    assert len(messages) == 3
    assert messages[0]["content"] == "First message"
    assert messages[0]["role"] == "user"
    assert messages[1]["content"] == "First response"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["content"] == "Second message"
    assert messages[2]["role"] == "user"


async def test_multiple_sessions_isolate_messages(store):
    """Messages from different sessions should not leak between sessions."""
    session1 = await store["create_session"](title="Session 1")
    session2 = await store["create_session"](title="Session 2")

    await store["create_message"](
        session_id=session1["id"],
        role="user",
        content="Message for session 1",
        is_complete=True,
    )

    await store["create_message"](
        session_id=session2["id"],
        role="user",
        content="Message for session 2",
        is_complete=True,
    )

    msgs1 = await store["list_messages"](session1["id"])
    msgs2 = await store["list_messages"](session2["id"])

    assert len(msgs1) == 1
    assert len(msgs2) == 1
    assert msgs1[0]["content"] == "Message for session 1"
    assert msgs2[0]["content"] == "Message for session 2"
