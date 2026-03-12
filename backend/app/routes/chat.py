"""Chat routes: send messages, answer questions, SSE stream."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.models.schemas import MessageAnswer, MessageResponse, MessageSend, MessageSendResponse
from app.services import claude_runner, session_store
from app.services.event_store import event_stream
from app.services.stream_broker import session_broker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["chat"])


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}/messages
# ---------------------------------------------------------------------------

@router.get("/messages")
async def get_messages(
    session_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await session_store.list_messages(session_id, limit=limit, offset=offset)
    total = await session_store.count_messages(session_id)
    return JSONResponse(
        content=[MessageResponse(**m).model_dump() for m in messages],
        headers={
            "X-Total-Count": str(total),
            "X-Limit": str(limit),
            "X-Offset": str(offset),
        },
    )


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/messages
# ---------------------------------------------------------------------------

@router.post("/messages", response_model=MessageSendResponse, status_code=202)
async def send_message(session_id: str, body: MessageSend):
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Persist the user message
    msg = await session_store.create_message(
        session_id=session_id,
        role="user",
        content=body.content,
        is_complete=True,
    )

    # Spawn claude runner as a background task
    asyncio.create_task(
        claude_runner.send_message(
            session_id=session_id,
            prompt=body.content,
            images=body.images,
        )
    )

    return MessageSendResponse(messageId=msg["id"], status="streaming")


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/answer
# ---------------------------------------------------------------------------

@router.post("/answer", response_model=MessageSendResponse, status_code=202)
async def answer_question(session_id: str, body: MessageAnswer):
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Compose the prompt that tells Claude the user answered its question
    prompt = (
        f"You previously asked: '{body.question_text}'. "
        f"The user answered: '{body.answer}'. Continue."
    )

    # Persist as a user message
    msg = await session_store.create_message(
        session_id=session_id,
        role="user",
        content=prompt,
        is_complete=True,
    )

    # Spawn claude runner
    asyncio.create_task(
        claude_runner.send_message(
            session_id=session_id,
            prompt=prompt,
        )
    )

    return MessageSendResponse(messageId=msg["id"], status="streaming")


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}/stream  (SSE)
# ---------------------------------------------------------------------------

@router.get("/stream")
async def stream_events(session_id: str, request: Request):
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        # Send an initial connection event
        yield _sse({"type": "connected", "session_id": session_id,
                     "streaming": claude_runner.is_session_streaming(session_id)})

        subscription = session_broker.subscribe(session_id)
        ping_interval = 15  # seconds

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
# GET /api/sessions/{session_id}/events  (Event-sourced SSE)
# ---------------------------------------------------------------------------

@router.get("/events")
async def stream_events_v2(
    session_id: str,
    request: Request,
    since: int = Query(default=0, ge=0),
):
    """Event-sourced SSE endpoint. Serves persisted events from the DB.

    Unlike /stream which uses an in-memory broker, this endpoint:
    - Catches up from the event log (supports ?since=N for cursor-based resume)
    - Waits for new events via asyncio.Condition notification
    - Survives backend restarts (events are in SQLite)
    - Enables seamless cross-device handoff
    """
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        # Send connected event with current streaming status
        yield _sse({"type": "connected", "session_id": session_id,
                     "streaming": claude_runner.is_session_streaming(session_id)})

        try:
            async for evt in event_stream(session_id, since_seq=since):
                if await request.is_disconnected():
                    break
                yield _sse({
                    "seq": evt["seq"],
                    "type": evt["event_type"],
                    "data": evt["data"],
                    "ts": evt["created_at"],
                })
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _with_keepalive_v2(event_generator(), 15, request),
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

async def _with_keepalive_v2(gen, interval: int, request: Request):
    """Wrap a generator with keepalive pings and disconnect detection."""
    gen_iter = gen.__aiter__()
    while True:
        if await request.is_disconnected():
            break
        try:
            item = await asyncio.wait_for(gen_iter.__anext__(), timeout=interval)
            yield item
        except asyncio.TimeoutError:
            yield _sse({"type": "ping"})
        except StopAsyncIteration:
            break


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


async def _with_keepalive(subscription, interval: int, request: Request):
    """Wrap an async generator with periodic keepalive pings.

    Also checks if the client has disconnected.
    """
    sub_iter = subscription.__aiter__()
    while True:
        if await request.is_disconnected():
            break
        try:
            event = await asyncio.wait_for(sub_iter.__anext__(), timeout=interval)
            yield event
        except asyncio.TimeoutError:
            # Send keepalive ping
            yield {"type": "ping"}
        except StopAsyncIteration:
            break
