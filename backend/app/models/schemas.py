"""Pydantic models for Nexus v2 API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class SessionCreate(BaseModel):
    title: Optional[str] = None
    role: Optional[str] = None          # e.g. "coding", "product", "writing"
    project_name: Optional[str] = None  # e.g. "nexus-v2"
    project_dir: Optional[str] = None   # e.g. "services/nexus-v2"


class SessionResponse(BaseModel):
    id: str
    title: str
    claude_session_id: str
    status: str
    role: Optional[str] = None
    project_name: Optional[str] = None
    project_dir: Optional[str] = None
    created_at: str
    updated_at: str


class SessionDetail(SessionResponse):
    messages: list[MessageResponse] = []


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class MessageSend(BaseModel):
    content: str
    images: Optional[list[str]] = None  # base64 strings


class MessageAnswer(BaseModel):
    answer: str
    question_text: str = Field(alias="questionText")

    model_config = {"populate_by_name": True}


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    tool_calls: Optional[str] = None
    thinking: Optional[str] = None
    is_complete: bool
    status: str = "complete"
    created_at: str


class MessageSendResponse(BaseModel):
    message_id: str = Field(alias="messageId")
    status: str = "streaming"

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

class HookEvent(BaseModel):
    """Raw hook event from Claude Code hooks."""
    session_id: Optional[str] = None
    event_type: Optional[str] = None
    tool_name: Optional[str] = None
    # Accept any additional fields
    model_config = {"extra": "allow"}


class HookEventResponse(BaseModel):
    id: str
    session_id: Optional[str]
    event_type: Optional[str]
    tool_name: Optional[str]
    payload: str
    created_at: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    active_sessions: int = Field(alias="activeSessions", default=0)

    model_config = {"populate_by_name": True, "serialize_by_alias": True}
