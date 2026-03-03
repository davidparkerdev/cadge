"""Shared fixtures for Nexus v2 backend integration tests."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_sse_events(text: str) -> list[dict[str, Any]]:
    """Parse an SSE text stream into a list of JSON event dicts.

    Each SSE event is a line like ``data: {...}\n\n``. This helper extracts
    and deserialises every ``data:`` payload.
    """
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[len("data: "):]))
            except json.JSONDecodeError:
                pass
    return events


async def create_test_session(
    client: httpx.AsyncClient,
    title: str | None = None,
) -> dict[str, Any]:
    """POST to create a session and return the response JSON dict."""
    body = {"title": title} if title else {}
    resp = await client.post("/api/sessions", json=body)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def client(tmp_path):
    """Yield an httpx.AsyncClient wired to the FastAPI app.

    * Uses a per-test temp SQLite database (via ``tmp_path``).
    * Patches ``claude_runner`` so no subprocess is spawned.
    * Explicitly calls ``init_db()`` since ASGITransport does not run
      the FastAPI lifespan.
    """
    db_path = str(tmp_path / "test.db")

    with patch("app.services.session_store.DB_PATH", db_path):
        # Initialise the database schema (lifespan won't run under ASGITransport)
        from app.services.session_store import init_db
        await init_db()

        with patch("app.routes.chat.claude_runner") as mock_runner:
            mock_runner.send_message = AsyncMock()
            mock_runner.is_session_streaming.return_value = False
            mock_runner.active_session_count.return_value = 0

            # Also patch the health endpoint's reference to claude_runner
            with patch("app.main.claude_runner", mock_runner):
                from app.main import app

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as c:
                    yield c
