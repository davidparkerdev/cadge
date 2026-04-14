# Cadge

Provider-agnostic AI development companion UI. Supports two LLM backends as first-class citizens: Claude Code CLI sessions and the local MLX Server (Apple Silicon, OpenAI-compatible). Provides session management, streaming chat, per-turn focus tracking, rich stats, and an agentic tool suite for MLX (read_file, write_file, bash, grep, ls, glob).

## Development Setup

### Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 33401
```

### Frontend
```bash
cd frontend
npm install
npm run dev    # Runs on port 33400
```

### Quick Start (both)
```bash
task install   # Install all dependencies
task start     # Start both API and UI
```

## Configuration

- **`CADGE_PROJECT_ROOT`** -- Environment variable for resolving relative `project_dir` paths when creating sessions. Defaults to the cadge repository root when not set. In the TheLab monorepo, set this to the monorepo root so project paths resolve correctly.
- **`MLX_SERVER_URL`** -- Base URL for the local MLX Server. Defaults to `http://localhost:33339`.

## Provider System

Cadge uses a provider abstraction layer (`app/services/providers/`) to support multiple LLM backends:

| Provider | ID | How it works |
|---|---|---|
| Claude Code | `claude-code` | Spawns `claude` CLI subprocesses with `--output-format stream-json` |
| MLX Server | `mlx-server` | HTTP streaming to the local MLX Server (`/v1/chat/completions`) with native OpenAI tool-calling + an agent loop |

Each session stores its `provider_id` and `model`. The provider is selected at session creation time.

To add a new provider: create a class in `app/services/providers/` implementing `BaseProvider`, then register it in `registry.py`.

## Git Submodule (TheLab)

This repo is used as a **git submodule** in the [TheLab monorepo](https://github.com/davidparkercodes/the-lab) at `domains/agentic-development/cadge/`.

### Submodule Workflow

1. Make changes inside this repo directory
2. **Commit and push inside this repo first** -- `git add`, `git commit`, `git push` from within `domains/agentic-development/cadge/`
3. Then, in the monorepo root, stage the submodule pointer: `git add domains/agentic-development/cadge`
4. Commit the pointer update in the monorepo

**AI Agent instructions:** Always commit and push inside the submodule before committing the monorepo pointer update. Never use `git add -A` from the monorepo root without checking submodule state first.

## Anti-Patterns (NEVER DO THESE)

- **NO POLLING.** Never use `setInterval`, `setTimeout` loops, or any form of polling to check for data. The entire architecture is built on SSE streaming. If data isn't appearing, the SSE pipeline is broken -- fix the pipeline, don't add polling around it.
- **NO DB POLLING.** Never periodically query the database to check for new messages. Messages flow through SSE. If SSE isn't delivering, fix SSE.
- **NO RACE CONDITION WORKAROUNDS.** If there's a race condition (e.g. SSE not connected when events fire), fix the sequencing so the race can't happen. Don't add fallback mechanisms to paper over timing bugs.
- **KEEP IT SIMPLE.** The whole point of v2 is simplicity over v1. If a fix adds significant complexity (new refs, intervals, cleanup effects), step back and find the simpler solution.

## Overview

- **Tech:** React + TypeScript + Tailwind (frontend), Python/FastAPI (backend)
- **Ports:** 33400 (UI), 33401 (API)
- **Database:** SQLite (local, at backend/cadge.db)

## Architecture

Provider-agnostic architecture with pluggable LLM backends:

- **Provider layer:** `app/services/providers/` with `BaseProvider` ABC, registry, and per-provider implementations
- **Claude Code provider:** Spawns `claude -p` subprocess, parses `--output-format stream-json` stdout
- **MLX Server provider:** HTTP streaming via `httpx` to `/v1/chat/completions` (OpenAI-compatible); runs an agent loop that executes tools locally and feeds results back until the model stops requesting tools
- **Facade:** `claude_runner.py` delegates to the correct provider based on session's `provider_id`
- **Streaming:** All providers emit normalized events through the same SSE pipeline (no DB polling)
- **Session state:** Each session stores `provider_id` and `model` alongside existing fields
- **Multi-device:** Multiple SSE clients per session for seamless Mac/iPhone handoff

## API Endpoints

### Sessions
```
POST   /api/sessions              - Create new session
GET    /api/sessions              - List sessions
GET    /api/sessions/:id          - Get session details
DELETE /api/sessions/:id          - Delete session
```

### Chat
```
POST   /api/sessions/:id/messages - Send a message (routes to provider, returns stream)
POST   /api/sessions/:id/answer   - Answer a question (continues session)
GET    /api/sessions/:id/events   - SSE event stream (cursor-based, supports reconnection)
```

### Providers
```
GET    /api/providers              - List available providers
GET    /api/providers/:id          - Get provider details
GET    /api/providers/:id/models   - List models for a provider
GET    /api/providers/:id/status   - Check provider availability
```

### Hooks
```
POST   /api/hooks/event           - Receive hook events from Claude Code
GET    /api/hooks/events          - List recent hook events (paginated, limit/offset)
GET    /api/hooks/stream          - SSE stream of hook events
```

### Health
```
GET    /api/health                - Health check
```

## Frontend Routes
```
/                    - Session list (home)
/session/:id         - Chat view
```
