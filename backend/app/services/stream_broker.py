"""Per-session SSE broadcast broker.

Each session has zero or more subscribed clients. Each client gets its own
asyncio.Queue so slow readers don't block others. The broker is a singleton
used by claude_runner (publish) and the SSE route (subscribe).

Includes a replay buffer so late-joining clients (e.g. new-session navigation
race) catch up with in-progress streams without missing events.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# Event types that mark the start of a new streaming run
_STREAM_START_TYPES = frozenset({"start", "message_start"})
# Event types that mark the end of a streaming run
_STREAM_END_TYPES = frozenset({"done", "message_stop", "cancelled", "error"})


class StreamBroker:
    """Manages per-session, multi-client SSE event distribution.

    Maintains a per-session replay buffer of events from the current streaming
    run.  When a new client subscribes, buffered events are replayed into its
    queue so it sees the full stream even if it connected late.
    """

    def __init__(self, replay_buffer_size: int = 2000) -> None:
        # session_id -> set of asyncio.Queue
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        # session_id -> list of events from the current streaming run
        self._replay_buffer: dict[str, list[dict]] = {}
        self._buffer_size = replay_buffer_size

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe
    # ------------------------------------------------------------------

    async def subscribe(self, session_id: str) -> AsyncGenerator[dict, None]:
        """Yield events for *session_id* until the client disconnects.

        Late-joining clients receive buffered events from the current
        streaming run before transitioning to live events.
        """
        queue: asyncio.Queue = asyncio.Queue()

        # Register subscriber FIRST, then replay buffer.  Since both are
        # synchronous (no awaits), no publish() call can interleave, so
        # we won't miss events or get duplicates.
        self._subscribers.setdefault(session_id, set()).add(queue)

        # Replay buffered events from the current streaming run
        buffered = list(self._replay_buffer.get(session_id, []))
        for event in buffered:
            queue.put_nowait(event)

        logger.info(
            "Client subscribed to session %s (total: %d, replayed: %d)",
            session_id,
            len(self._subscribers[session_id]),
            len(buffered),
        )
        try:
            while True:
                event = await queue.get()
                # A None sentinel means "shut down this subscription"
                if event is None:
                    break
                yield event
        finally:
            self._remove_client(session_id, queue)

    def _remove_client(self, session_id: str, queue: asyncio.Queue) -> None:
        clients = self._subscribers.get(session_id)
        if clients:
            clients.discard(queue)
            if not clients:
                del self._subscribers[session_id]
        logger.info(
            "Client unsubscribed from session %s (remaining: %d)",
            session_id,
            len(self._subscribers.get(session_id, set())),
        )

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def publish(self, session_id: str, event: dict) -> None:
        """Broadcast *event* to every subscriber and buffer for replay."""
        event_type = event.get("type", "")

        # -- Replay buffer management --
        if event_type in _STREAM_START_TYPES:
            # New streaming run: reset buffer
            self._replay_buffer[session_id] = []

        # Buffer events during an active streaming run
        buf = self._replay_buffer.get(session_id)
        if buf is not None:
            buf.append(event)
            if len(buf) > self._buffer_size:
                buf.pop(0)

        if event_type in _STREAM_END_TYPES:
            # Streaming done: clear buffer (no need to replay completed runs)
            self._replay_buffer.pop(session_id, None)

        # -- Broadcast to live subscribers --
        clients = self._subscribers.get(session_id)
        if not clients:
            return
        for queue in clients:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Dropping event for a slow client on session %s", session_id
                )

    def close_session(self, session_id: str) -> None:
        """Send sentinel to all subscribers of a session so they terminate."""
        clients = self._subscribers.get(session_id)
        if not clients:
            return
        for queue in clients:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id, set()))

    def active_session_ids(self) -> list[str]:
        return list(self._subscribers.keys())


# ---------------------------------------------------------------------------
# Singleton instances
# ---------------------------------------------------------------------------

# Main session stream broker (claude subprocess events)
session_broker = StreamBroker()

# Hooks stream broker (hook events from Claude Code)
hooks_broker = StreamBroker()

# A fixed key for the global hooks stream
HOOKS_GLOBAL_KEY = "__hooks_global__"
