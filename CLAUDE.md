# Nexus v2

AI development companion UI built on top of Claude Code. Provides a custom chat interface with session management and hook event monitoring.

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

- **`NEXUS_PROJECT_ROOT`** — Environment variable for resolving relative `project_dir` paths when creating sessions. Defaults to the nexus-v2 repository root when not set. In the TheLab monorepo, set this to the monorepo root so project paths resolve correctly.

## Git Submodule (TheLab)

This repo is used as a **git submodule** in the [TheLab monorepo](https://github.com/davidparkercodes/the-lab) at `domains/agentic-development/nexus-v2/`.

### Submodule Workflow

1. Make changes inside this repo directory
2. **Commit and push inside this repo first** — `git add`, `git commit`, `git push` from within `domains/agentic-development/nexus-v2/`
3. Then, in the monorepo root, stage the submodule pointer: `git add domains/agentic-development/nexus-v2`
4. Commit the pointer update in the monorepo

**AI Agent instructions:** Always commit and push inside the submodule before committing the monorepo pointer update. Never use `git add -A` from the monorepo root without checking submodule state first.

## Anti-Patterns (NEVER DO THESE)

- **NO POLLING.** Never use `setInterval`, `setTimeout` loops, or any form of polling to check for data. The entire architecture is built on SSE streaming. If data isn't appearing, the SSE pipeline is broken — fix the pipeline, don't add polling around it.
- **NO DB POLLING.** Never periodically query the database to check for new messages. Messages flow through SSE. If SSE isn't delivering, fix SSE.
- **NO RACE CONDITION WORKAROUNDS.** If there's a race condition (e.g. SSE not connected when events fire), fix the sequencing so the race can't happen. Don't add fallback mechanisms to paper over timing bugs.
- **KEEP IT SIMPLE.** The whole point of v2 is simplicity over v1. If a fix adds significant complexity (new refs, intervals, cleanup effects), step back and find the simpler solution.

## Overview

- **Tech:** React + TypeScript + Tailwind (frontend), Python/FastAPI (backend)
- **Ports:** 33400 (UI), 33401 (API)
- **Database:** SQLite (local, at backend/nexus_v2.db)

## Architecture

Unlike Nexus v1 which spawned and managed Claude CLI processes with a separate worker service, Nexus v2 uses a simplified architecture:

- **Message sending:** `claude -p "prompt" --session-id X --output-format stream-json` one-shot subprocess calls
- **Streaming:** Stdout JSON parsed line-by-line and forwarded directly to clients via SSE (no DB polling)
- **Session state:** Managed by Claude Code internally (`~/.cache/claude-sdk/sessions/`)
- **Observability:** Claude Code hooks fire on lifecycle events and POST to the API
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
POST   /api/sessions/:id/messages - Send a message (spawns claude -p, returns stream)
POST   /api/sessions/:id/answer   - Answer a question (continues session)
GET    /api/sessions/:id/stream   - SSE stream (multi-client broadcast)
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
