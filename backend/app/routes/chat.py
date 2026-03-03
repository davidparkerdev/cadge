"""Chat routes: send messages, answer questions, SSE stream."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models.schemas import MessageAnswer, MessageResponse, MessageSend, MessageSendResponse
from app.services import claude_runner, session_store
from app.services.stream_broker import session_broker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["chat"])


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}/messages
# ---------------------------------------------------------------------------

@router.get("/messages", response_model=list[MessageResponse])
async def get_messages(session_id: str):
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return await session_store.list_messages(session_id)


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
# Helpers
# ---------------------------------------------------------------------------

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
