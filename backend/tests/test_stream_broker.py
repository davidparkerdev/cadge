"""Unit tests for StreamBroker (no HTTP, pure asyncio)."""

from __future__ import annotations

import asyncio

import pytest

from app.services.stream_broker import StreamBroker


# ---------------------------------------------------------------------------
# Existing Tests
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


# ---------------------------------------------------------------------------
# NEX-278: Queue full / slow subscriber tests
# ---------------------------------------------------------------------------


async def test_queue_full_drops_events_without_crash():
    """When a subscriber's queue is full, publish() drops events gracefully."""
    # Small queue so we can fill it easily
    broker = StreamBroker(max_queue_size=5)
    session_id = "slow-sub"

    # Create a subscriber but don't consume events (simulating slow client)
    gen = broker.subscribe(session_id)
    # Advance to the first yield point so the queue is registered
    await gen.__anext__.__wrapped__(gen) if hasattr(gen.__anext__, '__wrapped__') else None  # noqa
    # Actually: just use a task that pauses before reading
    received: list[dict] = []
    pause = asyncio.Event()

    async def slow_reader():
        async for event in broker.subscribe(session_id):
            received.append(event)
            if len(received) == 1:
                # Pause after first event -- queue will fill up
                await pause.wait()

    task = asyncio.create_task(slow_reader())
    await asyncio.sleep(0.01)

    # Publish more events than the queue can hold.
    # The reader will consume 1, then pause. The remaining queue capacity
    # is (max_queue_size - 0) since the reader got the first one already,
    # but timing varies.  Publish well over the limit.
    for i in range(20):
        broker.publish(session_id, {"type": "data", "i": i})

    # The broker should NOT have raised -- some events were dropped.
    # Let the reader finish.
    pause.set()
    await asyncio.sleep(0.01)
    broker.close_session(session_id)
    await asyncio.sleep(0.01)
    await task

    # Reader got some events but NOT all 20 (some were dropped).
    assert len(received) < 20
    assert len(received) >= 1  # Got at least the first one


async def test_queue_full_does_not_affect_other_subscribers():
    """A slow subscriber's full queue doesn't prevent fast subscribers from
    getting events."""
    broker = StreamBroker(max_queue_size=3)
    session_id = "mixed-speed"
    fast_received: list[dict] = []
    slow_received: list[dict] = []
    slow_pause = asyncio.Event()

    async def fast_reader():
        async for event in broker.subscribe(session_id):
            fast_received.append(event)

    async def slow_reader():
        async for event in broker.subscribe(session_id):
            slow_received.append(event)
            if not slow_pause.is_set():
                await slow_pause.wait()

    fast_task = asyncio.create_task(fast_reader())
    slow_task = asyncio.create_task(slow_reader())
    await asyncio.sleep(0.01)

    # Publish 10 events -- fast reader keeps up, slow reader blocks after 1
    for i in range(10):
        broker.publish(session_id, {"type": "data", "i": i})
        await asyncio.sleep(0.001)  # Let fast reader consume

    await asyncio.sleep(0.05)

    # Fast reader should have all 10
    assert len(fast_received) == 10

    # Unblock slow reader, close session
    slow_pause.set()
    await asyncio.sleep(0.01)
    broker.close_session(session_id)
    await asyncio.sleep(0.01)
    await fast_task
    await slow_task

    # Slow reader got fewer because events were dropped
    assert len(slow_received) < 10


# ---------------------------------------------------------------------------
# NEX-278: Subscriber cleanup tests
# ---------------------------------------------------------------------------


async def test_generator_close_cleans_up_subscriber():
    """When the async generator is closed (client disconnect), the subscriber
    is removed from the broker."""
    broker = StreamBroker()
    session_id = "cleanup-test"

    gen = broker.subscribe(session_id)
    # Start the generator -- this registers the subscriber
    task = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0.01)
    assert broker.subscriber_count(session_id) == 1

    # Close the generator (simulates client disconnect)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await gen.aclose()
    await asyncio.sleep(0.01)

    # Subscriber should be cleaned up
    assert broker.subscriber_count(session_id) == 0


async def test_task_cancellation_cleans_up_subscriber():
    """If the reader task is cancelled (e.g. HTTP disconnect), the subscriber
    is still cleaned up via the finally block."""
    broker = StreamBroker()
    session_id = "cancel-cleanup"

    async def reader():
        async for _ in broker.subscribe(session_id):
            pass

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    assert broker.subscriber_count(session_id) == 1

    # Cancel the task (simulates HTTP client disconnect)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.01)

    assert broker.subscriber_count(session_id) == 0


async def test_multiple_disconnects_no_leak():
    """Subscribing and disconnecting many times should not leak memory."""
    broker = StreamBroker()
    session_id = "leak-test"

    for _ in range(50):
        async def reader():
            async for _ in broker.subscribe(session_id):
                pass

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.005)
        assert broker.subscriber_count(session_id) == 1

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.005)

    # After 50 subscribe/disconnect cycles, no subscribers should remain
    assert broker.subscriber_count(session_id) == 0
    assert broker.total_subscriber_count() == 0


async def test_unsubscribe_method():
    """The explicit unsubscribe() method should terminate and remove a
    subscriber."""
    broker = StreamBroker()
    session_id = "unsub-test"
    received: list[dict] = []

    # We need access to the queue to call unsubscribe().
    # In real usage, the SSE route would hold a reference.
    # For testing, we reach into internals after subscribing.
    gen = broker.subscribe(session_id)

    async def reader():
        async for event in gen:
            received.append(event)

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    assert broker.subscriber_count(session_id) == 1

    # Get the queue reference from internals
    queues = broker._subscribers[session_id]
    queue = next(iter(queues))

    # Publish one event, then unsubscribe
    broker.publish(session_id, {"type": "data"})
    await asyncio.sleep(0.01)
    broker.unsubscribe(session_id, queue)
    await asyncio.sleep(0.01)
    await task

    assert broker.subscriber_count(session_id) == 0
    assert len(received) >= 1


# ---------------------------------------------------------------------------
# NEX-278: Close session with full queue
# ---------------------------------------------------------------------------


async def test_close_session_with_full_queue():
    """close_session() should still terminate subscribers even if the queue
    is full (sentinel must get through)."""
    broker = StreamBroker(max_queue_size=3)
    session_id = "full-close"
    done = asyncio.Event()

    async def stalled_reader():
        """Reader that stops consuming after registering."""
        gen = broker.subscribe(session_id)
        # Read nothing -- just wait for generator to terminate
        async for _ in gen:
            pass
        done.set()

    task = asyncio.create_task(stalled_reader())
    await asyncio.sleep(0.01)

    # Fill the queue completely
    for i in range(5):
        broker.publish(session_id, {"type": "filler", "i": i})

    # Queue is full.  close_session should still get sentinel through.
    broker.close_session(session_id)
    await asyncio.sleep(0.05)

    # The reader task should have terminated
    assert done.is_set()
    await task
    assert broker.subscriber_count(session_id) == 0


# ---------------------------------------------------------------------------
# NEX-278: total_subscriber_count introspection
# ---------------------------------------------------------------------------


async def test_total_subscriber_count():
    """total_subscriber_count() should reflect subscribers across all sessions."""
    broker = StreamBroker()

    assert broker.total_subscriber_count() == 0

    async def reader(sid: str):
        async for _ in broker.subscribe(sid):
            pass

    t1 = asyncio.create_task(reader("session-a"))
    t2 = asyncio.create_task(reader("session-a"))
    t3 = asyncio.create_task(reader("session-b"))
    await asyncio.sleep(0.01)

    assert broker.total_subscriber_count() == 3
    assert broker.subscriber_count("session-a") == 2
    assert broker.subscriber_count("session-b") == 1

    broker.close_session("session-a")
    broker.close_session("session-b")
    await asyncio.sleep(0.01)
    await t1
    await t2
    await t3

    assert broker.total_subscriber_count() == 0
