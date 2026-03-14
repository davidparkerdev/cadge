"""Fire-and-forget push client for Observatory.

Nexus v2 is a dumb UI — all observability data goes to Observatory.
Failures are logged and silently ignored (never block Nexus v2 operations).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OBSERVATORY_API = "http://localhost:33420"

_client: httpx.AsyncClient | None = None

# Set to True during shutdown to prevent in-flight tasks from
# creating a new httpx.AsyncClient after close() has been called.
_shutdown: bool = False

# Backpressure: track pending fire-and-forget tasks.
# If more than _MAX_PENDING tasks are in-flight, new pushes are skipped
# to prevent unbounded memory growth when Observatory is slow or down.
_MAX_PENDING = 50
_pending_tasks: set[asyncio.Task] = set()


async def close() -> None:
    """Close the HTTP client. Call during app shutdown."""
    global _client, _shutdown
    _shutdown = True
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient | None:
    """Get or create the HTTP client. Returns None if shutdown."""
    global _client
    if _shutdown:
        return None
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=5.0)
    return _client


def _task_done(task: asyncio.Task) -> None:
    """Callback to remove completed tasks from the pending set."""
    _pending_tasks.discard(task)


def push_event(endpoint: str, data: dict[str, Any]) -> None:
    """Fire-and-forget POST to Observatory. Never blocks, never raises.

    Applies backpressure: if more than _MAX_PENDING tasks are in-flight,
    the push is silently skipped to avoid unbounded memory growth.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop — skip silently
        return

    if len(_pending_tasks) >= _MAX_PENDING:
        logger.debug(
            "Observatory backpressure: %d pending tasks, skipping push to %s",
            len(_pending_tasks), endpoint,
        )
        return

    task = loop.create_task(_async_push(endpoint, data))
    _pending_tasks.add(task)
    task.add_done_callback(_task_done)


async def _async_push(endpoint: str, data: dict[str, Any]) -> None:
    """Async POST with error suppression."""
    try:
        client = _get_client()
        if client is None:
            return  # Shutdown in progress, skip silently
        await client.post(f"{OBSERVATORY_API}{endpoint}", json=data)
    except Exception as exc:
        logger.debug("Observatory push failed (%s): %s", endpoint, exc)


def push_session_event(
    session_id: str,
    event_type: str,  # "start" | "complete" | "failure" | "cancel"
    title: str = "",
    role: str | None = None,
    project_name: str | None = None,
    project_dir: str | None = None,
    pid: int | None = None,
    exit_code: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    error: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    """Push a session lifecycle event to Observatory."""
    push_event("/api/observatory/stargate/ingest/session", {
        "session_id": session_id,
        "event_type": event_type,
        "title": title,
        "role": role,
        "project_name": project_name,
        "project_dir": project_dir,
        "pid": pid,
        "exit_code": exit_code,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "error": error,
        "duration_seconds": duration_seconds,
    })


def push_hook_event(
    event_type: str,
    session_id: str | None = None,
    tool_name: str | None = None,
    payload: dict | None = None,
    summary: str | None = None,
) -> None:
    """Push a hook event to Observatory."""
    push_event("/api/observatory/stargate/ingest/hook", {
        "session_id": session_id,
        "event_type": event_type,
        "tool_name": tool_name,
        "payload": payload or {},
        "summary": summary,
    })


def push_request_metric(
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    slow: bool = False,
) -> None:
    """Push a request metric to Observatory."""
    push_event("/api/observatory/stargate/ingest/request", {
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "slow": slow,
    })


def push_frontend_error(
    level: str,
    category: str,
    message: str,
    error: str | None = None,
    data: dict | None = None,
) -> None:
    """Push a frontend error/warn to Observatory via the hook event ingestion endpoint.

    Uses the existing stargate_hook_events table with:
    - session_id: "frontend" (constant — not tied to a Claude session)
    - event_type: "frontend_error" or "frontend_warn"
    - tool_name: the logger category/component
    - payload: error details
    """
    event_type = "frontend_error" if level == "error" else "frontend_warn"
    push_hook_event(
        event_type=event_type,
        session_id="frontend",
        tool_name=category,
        payload={
            "message": message,
            "error": error,
            "data": data,
        },
        summary=f"[{category}] {message}",
    )
