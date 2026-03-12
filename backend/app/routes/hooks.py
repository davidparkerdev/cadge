"""Hook event ingestion and SSE streaming.

Claude Code hooks POST raw JSON events here. They are persisted and
broadcast to any connected SSE clients on the hooks stream.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.services import session_store
from app.services.observatory_client import push_hook_event
from app.services.stream_broker import HOOKS_GLOBAL_KEY, hooks_broker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hooks", tags=["hooks"])


# ---------------------------------------------------------------------------
# POST /api/hooks/event
# ---------------------------------------------------------------------------

@router.post("/event", status_code=201)
async def receive_hook_event(request: Request):
    """Ingest a raw hook event from a Claude Code hook script."""
    raw = await request.json()

    event_type = raw.get("event_type") or raw.get("type")
    hook_session_id = raw.get("session_id")
    tool_name = raw.get("tool_name") or raw.get("tool", {}).get("name")

    evt = await session_store.create_hook_event(
        event_type=event_type,
        session_id=hook_session_id,
        tool_name=tool_name,
        payload=raw,
    )

    # Broadcast to hooks SSE subscribers
    hooks_broker.publish(HOOKS_GLOBAL_KEY, {
        "id": evt["id"],
        "event_type": event_type,
        "session_id": hook_session_id,
        "tool_name": tool_name,
        "payload": raw,
        "created_at": evt["created_at"],
    })

    # Push to Observatory (fire-and-forget)
    push_hook_event(
        event_type=event_type,
        session_id=hook_session_id,
        tool_name=tool_name,
        payload=raw,
    )

    return {"id": evt["id"], "status": "received"}


# ---------------------------------------------------------------------------
# GET /api/hooks/events  (paginated list)
# ---------------------------------------------------------------------------

@router.get("/events")
async def list_hook_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Return recent hook events with pagination."""
    events, total = await session_store.list_hook_events(limit=limit, offset=offset)
    return JSONResponse(
        content={"events": events, "total": total, "limit": limit, "offset": offset},
        headers={
            "X-Total-Count": str(total),
            "X-Limit": str(limit),
            "X-Offset": str(offset),
        },
    )


# ---------------------------------------------------------------------------
# GET /api/hooks/stream  (SSE)
# ---------------------------------------------------------------------------

@router.get("/stream")
async def stream_hook_events(request: Request):
    """SSE stream of all hook events (for Command Center)."""

    async def event_generator():
        yield _sse({"type": "connected"})

        subscription = hooks_broker.subscribe(HOOKS_GLOBAL_KEY)
        ping_interval = 15

        try:
            async for event in _with_keepalive(subscription, ping_interval, request):
                yield _sse(event)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _with_keepalive(subscription, interval: int, request: Request):
    sub_iter = subscription.__aiter__()
    while True:
        if await request.is_disconnected():
            break
        try:
            event = await asyncio.wait_for(sub_iter.__anext__(), timeout=interval)
            yield event
        except asyncio.TimeoutError:
            yield {"type": "ping"}
        except StopAsyncIteration:
            break
