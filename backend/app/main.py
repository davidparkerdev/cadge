"""Cadge Backend - FastAPI application.

A backend for Cadge, a UI on top of Claude Code. Manages chat sessions,
spawns claude CLI subprocesses, and streams events to clients via SSE.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import psutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from thelab_observability import ObservabilityMiddleware, setup_logging

from app.middleware import RequestMetricsMiddleware
from app.routes import chat, hooks, logs, providers, sessions, settings
from app.services import claude_runner, observatory_client
from app.services.claude_runner import cancel_session
from app.services.providers.registry import all_providers
from app.services.session_store import DB_PATH, _connect_db, cleanup_old_hook_events, init_db
from app.services.stream_broker import hooks_broker, session_broker

# Replace logging.basicConfig with structured logging
setup_logging("cadge-api", json_output=False)

logger = logging.getLogger(__name__)

# Startup timestamp for uptime tracking
_start_time = datetime.now(timezone.utc)
_start_monotonic = time.monotonic()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

async def _periodic_cleanup():
    """Run DB cleanup tasks periodically to prevent unbounded growth."""
    while True:
        try:
            await asyncio.sleep(6 * 3600)  # Every 6 hours
            from app.services.event_store import cleanup_old_events
            deleted_events = await cleanup_old_events(max_age_days=30)
            deleted_hooks = await cleanup_old_hook_events(max_age_days=7)
            # Checkpoint WAL to prevent unbounded WAL file growth
            async with _connect_db() as db:
                await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info(
                "Periodic cleanup: %d events, %d hook events, WAL checkpointed",
                deleted_events, deleted_hooks,
            )
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("Periodic cleanup failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Cadge backend starting up")
    await init_db()
    await cleanup_old_hook_events(max_age_days=7)
    # Initialize event store and clean up old events
    from app.services.event_store import init_events_table, cleanup_old_events
    await init_events_table()
    from app.services.settings_store import init_settings_table
    await init_settings_table()
    await cleanup_old_events(max_age_days=30)

    # Start periodic cleanup task
    cleanup_task = asyncio.create_task(_periodic_cleanup())

    yield

    # Cancel periodic cleanup
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    logger.info("Cadge backend shutting down")
    # Cancel all active provider sessions
    from app.services.providers.claude_code import _active_processes as _claude_active
    for sid in list(_claude_active.keys()):
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
    # Close observatory HTTP client
    await observatory_client.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Cadge API",
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
app.add_middleware(ObservabilityMiddleware, logger_name="cadge-api.http")

# Request metrics middleware (pushes to Observatory, no local storage)
app.add_middleware(RequestMetricsMiddleware)

# Include routers
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(hooks.router)
app.include_router(logs.router)
app.include_router(providers.router)
app.include_router(settings.router)


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
        async with _connect_db() as db:
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

    # DB file size
    db_size_mb = 0.0
    try:
        db_size_mb = round(DB_PATH.stat().st_size / 1024 / 1024, 2)
    except OSError:
        pass

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
                "size_mb": db_size_mb,
            },
            "stream_broker": {
                "status": "ok",
                "active_channels": broker_channels + hooks_channels,
                "total_subscribers": session_broker.total_subscriber_count() + hooks_broker.total_subscriber_count(),
            },
            "observatory": {
                "pending_tasks": len(observatory_client._pending_tasks),
            },
        },
    }
