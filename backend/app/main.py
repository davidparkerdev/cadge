"""Nexus v2 Backend - FastAPI application.

A backend for Nexus v2, a UI on top of Claude Code. Manages chat sessions,
spawns claude CLI subprocesses, and streams events to clients via SSE.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models.schemas import HealthResponse
from app.routes import chat, hooks, logs, sessions
from app.services import claude_runner
from app.services.session_store import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Nexus v2 backend starting up")
    await init_db()
    yield
    logger.info("Nexus v2 backend shutting down")


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
)

# Include routers
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(hooks.router)
app.include_router(logs.router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
async def health():
    return HealthResponse(activeSessions=claude_runner.active_session_count())
