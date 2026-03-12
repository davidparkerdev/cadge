"""Integration tests for session CRUD endpoints."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import create_test_session


# ---------------------------------------------------------------------------
# POST /api/sessions
# ---------------------------------------------------------------------------


async def test_create_session_default_title(client: httpx.AsyncClient):
    """Creating a session without a title should default to 'New Session'."""
    resp = await client.post("/api/sessions", json={})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "New Session"
    assert data["status"] == "active"
    assert "id" in data
    assert "claude_session_id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_session_custom_title(client: httpx.AsyncClient):
    """Creating a session with an explicit title should use it."""
    resp = await client.post("/api/sessions", json={"title": "My Project"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "My Project"


# ---------------------------------------------------------------------------
# GET /api/sessions
# ---------------------------------------------------------------------------


async def test_list_sessions_empty(client: httpx.AsyncClient):
    """Listing sessions when none exist should return an empty list."""
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_sessions_returns_created(client: httpx.AsyncClient):
    """Listing sessions should include previously created sessions."""
    await create_test_session(client, title="First")
    await create_test_session(client, title="Second")

    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 2
    titles = {s["title"] for s in sessions}
    assert titles == {"First", "Second"}


# ---------------------------------------------------------------------------
# GET /api/sessions/{id}
# ---------------------------------------------------------------------------


async def test_get_session_detail(client: httpx.AsyncClient):
    """Getting a session by ID should include a messages list."""
    session = await create_test_session(client, title="Detail Test")

    resp = await client.get(f"/api/sessions/{session['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == session["id"]
    assert data["title"] == "Detail Test"
    assert "messages" in data
    assert isinstance(data["messages"], list)


async def test_get_session_not_found(client: httpx.AsyncClient):
    """Requesting a non-existent session should return 404."""
    resp = await client.get("/api/sessions/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/sessions/{id}
# ---------------------------------------------------------------------------


async def test_delete_session(client: httpx.AsyncClient):
    """Deleting an existing session should return 204 and remove it."""
    session = await create_test_session(client)

    resp = await client.delete(f"/api/sessions/{session['id']}")
    assert resp.status_code == 204

    # Verify it is gone
    resp = await client.get(f"/api/sessions/{session['id']}")
    assert resp.status_code == 404


async def test_delete_session_not_found(client: httpx.AsyncClient):
    """Deleting a non-existent session should return 404."""
    resp = await client.delete("/api/sessions/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/sessions/{id}  (rename)
# ---------------------------------------------------------------------------


async def test_patch_session_rename(client: httpx.AsyncClient):
    """Renaming a session should update its title and return the updated session."""
    session = await create_test_session(client, title="Original Title")

    resp = await client.patch(
        f"/api/sessions/{session['id']}",
        json={"title": "Renamed Title"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Renamed Title"
    assert data["id"] == session["id"]
    # updated_at should have changed
    assert data["updated_at"] >= session["updated_at"]


async def test_patch_session_not_found(client: httpx.AsyncClient):
    """Patching a non-existent session should return 404."""
    resp = await client.patch(
        "/api/sessions/nonexistent-id",
        json={"title": "New Title"},
    )
    assert resp.status_code == 404


async def test_patch_session_empty_title(client: httpx.AsyncClient):
    """Patching with an empty title should be rejected (422)."""
    session = await create_test_session(client, title="Keep This")

    resp = await client.patch(
        f"/api/sessions/{session['id']}",
        json={"title": ""},
    )
    assert resp.status_code == 422


async def test_patch_session_null_title(client: httpx.AsyncClient):
    """Patching with null title should be rejected (422)."""
    session = await create_test_session(client, title="Keep This")

    resp = await client.patch(
        f"/api/sessions/{session['id']}",
        json={"title": None},
    )
    assert resp.status_code == 422


async def test_patch_session_whitespace_title(client: httpx.AsyncClient):
    """Patching with whitespace-only title should be rejected (422)."""
    session = await create_test_session(client, title="Keep This")

    resp = await client.patch(
        f"/api/sessions/{session['id']}",
        json={"title": "   "},
    )
    assert resp.status_code == 422
