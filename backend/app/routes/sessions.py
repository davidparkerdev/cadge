"""Session CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import SessionCreate, SessionDetail, SessionResponse, SessionUpdate
from app.routes.chat import cleanup_session_task
from app.services import claude_runner, session_store
from app.services.event_store import delete_session_events
from app.services.stream_broker import session_broker

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(body: SessionCreate | None = None):
    title = body.title if body else None
    role = body.role if body else None
    project_name = body.project_name if body else None
    project_dir = body.project_dir if body else None
    provider_id = body.provider_id if body else "claude-code"
    model = body.model if body else None
    session = await session_store.create_session(
        title=title,
        role=role,
        project_name=project_name,
        project_dir=project_dir,
        provider_id=provider_id,
        model=model,
    )
    return session


@router.get("", response_model=list[SessionResponse])
async def list_sessions():
    return await session_store.list_sessions()


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str):
    detail = await session_store.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, body: SessionUpdate):
    if not body.title or not body.title.strip():
        raise HTTPException(status_code=422, detail="Title must be a non-empty string")
    updated = await session_store.update_session(session_id, title=body.title.strip())
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return updated


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str):
    # Cancel any running subprocess first (safe even if session doesn't exist)
    await claude_runner.cancel_session(session_id)
    # Close SSE subscribers
    session_broker.close_session(session_id)
    # Delete the session row FIRST -- if it doesn't exist, 404 before touching events
    deleted = await session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    # Session confirmed deleted -- now clean up events and resources
    await delete_session_events(session_id)
    claude_runner.cleanup_session_resources(session_id)
    cleanup_session_task(session_id)
    return None


@router.post("/{session_id}/cancel")
async def cancel_session(session_id: str):
    """Cancel a running Claude subprocess."""
    was_running = await claude_runner.cancel_session(session_id)
    status = "cancelled" if was_running else "not_running"
    return {"status": status, "session_id": session_id}
