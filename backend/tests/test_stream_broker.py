"""Unit tests for StreamBroker (no HTTP, pure asyncio)."""

from __future__ import annotations

import asyncio

import pytest

from app.services.stream_broker import StreamBroker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_publish_subscribe():
    """A subscriber should receive events published to the same session."""
    broker = StreamBroker()
    session_id = "test-session"
    received: list[dict] = []

    async def reader():
        async for event in broker.subscribe(session_id):
            received.append(event)

    task = asyncio.create_task(reader())
    # Give the subscriber time to register
    await asyncio.sleep(0.01)

    broker.publish(session_id, {"type": "start"})
    broker.publish(session_id, {"type": "done"})
    await asyncio.sleep(0.01)

    # Close the session to terminate the subscriber
    broker.close_session(session_id)
    await asyncio.sleep(0.01)
    await task

    assert len(received) == 2
    assert received[0]["type"] == "start"
    assert received[1]["type"] == "done"


async def test_multi_subscriber():
    """Multiple subscribers on the same session should each get every event."""
    broker = StreamBroker()
    session_id = "multi-sub"
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def reader(target: list):
        async for event in broker.subscribe(session_id):
            target.append(event)

    task_a = asyncio.create_task(reader(received_a))
    task_b = asyncio.create_task(reader(received_b))
    await asyncio.sleep(0.01)

    broker.publish(session_id, {"type": "hello"})
    await asyncio.sleep(0.01)

    broker.close_session(session_id)
    await asyncio.sleep(0.01)
    await task_a
    await task_b

    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0]["type"] == "hello"
    assert received_b[0]["type"] == "hello"


async def test_close_session():
    """Closing a session should terminate all subscribers gracefully."""
    broker = StreamBroker()
    session_id = "close-test"
    done = asyncio.Event()

    async def reader():
        async for _ in broker.subscribe(session_id):
            pass
        # If we get here the generator terminated cleanly
        done.set()

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.01)

    broker.close_session(session_id)
    await asyncio.wait_for(done.wait(), timeout=1.0)
    await task

    assert broker.subscriber_count(session_id) == 0


async def test_subscriber_count():
    """subscriber_count should reflect the number of active subscribers."""
    broker = StreamBroker()
    session_id = "count-test"

    assert broker.subscriber_count(session_id) == 0

    queues: list[asyncio.Task] = []

    async def reader():
        async for _ in broker.subscribe(session_id):
            pass

    # Add two subscribers
    t1 = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    assert broker.subscriber_count(session_id) == 1

    t2 = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    assert broker.subscriber_count(session_id) == 2

    # Close session, both should exit
    broker.close_session(session_id)
    await asyncio.sleep(0.01)
    await t1
    await t2

    assert broker.subscriber_count(session_id) == 0
