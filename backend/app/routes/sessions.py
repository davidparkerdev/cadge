"""Session CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import SessionCreate, SessionDetail, SessionResponse
from app.services import session_store

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(body: SessionCreate | None = None):
    title = body.title if body else None
    role = body.role if body else None
    project_name = body.project_name if body else None
    project_dir = body.project_dir if body else None
    session = await session_store.create_session(
        title=title,
        role=role,
        project_name=project_name,
        project_dir=project_dir,
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


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str):
    deleted = await session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return None
