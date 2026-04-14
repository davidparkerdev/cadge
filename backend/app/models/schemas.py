"""Pydantic models for Cadge API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class SessionCreate(BaseModel):
    title: Optional[str] = None
    role: Optional[str] = None          # e.g. "coding", "product", "writing"
    project_name: Optional[str] = None  # e.g. "cadge"
    project_dir: Optional[str] = None   # e.g. "services/cadge"
    provider_id: str = "claude-code"    # e.g. "claude-code", "mlx-server"
    model: Optional[str] = None         # e.g. "llama-3.1-8b-instruct"


class SessionUpdate(BaseModel):
    title: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    title: str
    claude_session_id: str
    status: str
    role: Optional[str] = None
    project_name: Optional[str] = None
    project_dir: Optional[str] = None
    provider_id: str = "claude-code"
    model: Optional[str] = None
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

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("content must not be empty or whitespace-only")
        if len(v) > 200_000:
            raise ValueError("Content exceeds 200,000 character limit")
        return v

    @field_validator("images")
    @classmethod
    def validate_images(cls, v):
        if v is None:
            return v
        if len(v) > 5:
            raise ValueError("Maximum 5 images allowed")
        MAX_IMAGE_SIZE = 5_000_000  # 5MB per image as base64
        for i, img in enumerate(v):
            if len(img) > MAX_IMAGE_SIZE:
                raise ValueError(f"Image {i} exceeds 5MB limit")
        return v


class MessageAnswer(BaseModel):
    answer: str
    question_text: str = Field(alias="questionText")

    model_config = {"populate_by_name": True}

    @field_validator("answer")
    @classmethod
    def answer_length(cls, v: str) -> str:
        if len(v) > 50_000:
            raise ValueError("Answer exceeds 50,000 character limit")
        return v

    @field_validator("question_text")
    @classmethod
    def question_text_length(cls, v: str) -> str:
        if len(v) > 50_000:
            raise ValueError("Question text exceeds 50,000 character limit")
        return v


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    tool_calls: Optional[list] = None
    thinking: Optional[str] = None
    images: Optional[list[str]] = None
    is_complete: bool
    status: str = "complete"
    summary: Optional[str] = None
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
