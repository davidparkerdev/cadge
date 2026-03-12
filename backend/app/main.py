"""Nexus v2 Backend - FastAPI application.

A backend for Nexus v2, a UI on top of Claude Code. Manages chat sessions,
spawns claude CLI subprocesses, and streams events to clients via SSE.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
import psutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from thelab_observability import ObservabilityMiddleware, setup_logging

from app.middleware import RequestMetricsMiddleware
from app.routes import chat, hooks, logs, sessions
from app.services import claude_runner
from app.services.claude_runner import _active_processes, cancel_session
from app.services.session_store import DB_PATH, cleanup_old_hook_events, init_db
from app.services.stream_broker import hooks_broker, session_broker

# Replace logging.basicConfig with structured logging
setup_logging("nexus-v2-api", json_output=False)

logger = logging.getLogger(__name__)

# Startup timestamp for uptime tracking
_start_time = datetime.now(timezone.utc)
_start_monotonic = time.monotonic()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Nexus v2 backend starting up")
    await init_db()
    await cleanup_old_hook_events(max_age_days=7)
    # Initialize event store and clean up old events
    from app.services.event_store import init_events_table, cleanup_old_events
    await init_events_table()
    await cleanup_old_events(max_age_days=30)
    yield
    logger.info("Nexus v2 backend shutting down")
    # Kill all active Claude subprocesses
    active_session_ids = list(_active_processes.keys())
    for sid in active_session_ids:
        try:
            await cancel_session(sid)
            logger.info("Cancelled subprocess for session %s on shutdown", sid)
        except Exception:
            logger.warning("Failed to cancel session %s on shutdown", sid, exc_info=True)
    # Close all stream broker sessions
    for sid in session_broker.active_session_ids():
        session_broker.close_session(sid)
    for sid in hooks_broker.active_session_ids():
        hooks_broker.close_session(sid)
    # Note: events are persisted in SQLite, no cleanup needed on shutdown


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Nexus v2 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - allow all origins (personal tool on Tailnet)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "X-Limit", "X-Offset"],
)

# Observability middleware (request tracing with request_id, correlation_id, duration)
app.add_middleware(ObservabilityMiddleware, logger_name="nexus-v2-api.http")

# Request metrics middleware (pushes to Observatory, no local storage)
app.add_middleware(RequestMetricsMiddleware)

# Include routers
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(hooks.router)
app.include_router(logs.router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def _format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


@app.get("/api/health")
async def health():
    uptime_seconds = round(time.monotonic() - _start_monotonic, 1)

    # Check database
    db_status = "ok"
    db_detail = None
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            await db.execute("SELECT 1")
    except Exception as exc:
        db_status = "error"
        db_detail = str(exc)

    # Check stream broker
    broker_channels = len(session_broker.active_session_ids())
    hooks_channels = len(hooks_broker.active_session_ids())

    # Overall status
    status = "ok"
    if db_status == "error":
        status = "error"

    # Process memory usage
    proc = psutil.Process()
    mem = proc.memory_info()

    return {
        "status": status,
        "uptime_seconds": uptime_seconds,
        "uptime_formatted": _format_uptime(uptime_seconds),
        "started_at": _start_time.isoformat(),
        "active_sessions": claude_runner.active_session_count(),
        "memory": {
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
        },
        "components": {
            "database": {
                "status": db_status,
                "detail": db_detail,
            },
            "stream_broker": {
                "status": "ok",
                "active_channels": broker_channels + hooks_channels,
            },
        },
    }
