# Cadge

> **v0.1.0 -- Early development.** This is an active work-in-progress. When ready for general use, this project will move to [davidparkercodes/cadge](https://github.com/davidparkercodes/cadge).

A local-first command center for managing multiple AI coding agents. Run concurrent sessions across providers, monitor agent activity in real-time, and keep full history of everything your agents do.

Built as a daily-driver tool, not a demo. If you use AI coding agents heavily, Cadge gives you a single place to see and control all of them.

## What it does

- **Multi-provider sessions** -- Claude Code CLI and the local MLX Server (Apple Silicon). Pick per session.
- **Agentic tool suite (MLX)** -- Native OpenAI tool-calling with a built-in catalog (read_file, write_file, bash, grep, ls, glob). Runs a full agent loop inside Cadge.
- **Focus tracker + rich stats** -- Live per-turn focus indicator and a stats panel with context gauge, token counters, and tokens/sec.
- **Real-time streaming** -- SSE-based, no polling. Watch agents think, use tools, and spawn sub-agents live.
- **Session persistence** -- SQLite-backed. Full message history, event logs, and cross-device handoff.
- **Role-based prompting** -- 12 built-in roles (coding, product, QA, bug-fixing, etc.) shape agent behavior.
- **Hook event monitoring** -- Ingest Claude Code hook events to see what your agents are doing outside Cadge.
- **Multi-device** -- Multiple SSE clients per session. Start on your Mac, check on your phone.

## Tech stack

| Layer | Stack |
|-------|-------|
| Frontend | React 19, TypeScript, Tailwind, Vite |
| Backend | Python, FastAPI, SQLite (aiosqlite) |
| Streaming | Server-Sent Events (SSE) everywhere |
| Mobile | Capacitor (iOS) |

## Quick start

```bash
# Install dependencies
cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cd ../frontend && npm install

# Run both
cd .. && task start
```

Backend runs on port 33401, frontend on 33400.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CADGE_PROJECT_ROOT` | repo root | Base path for resolving project directories |
| `MLX_SERVER_URL` | `http://localhost:33339` | MLX Server API endpoint |

## Adding providers

Cadge uses a pluggable provider system. To add a new LLM backend:

1. Create a class in `backend/app/services/providers/` implementing `BaseProvider`
2. Register it in `registry.py`
3. It will appear in the provider selection when creating sessions

## Architecture

```
cadge/
├── backend/
│   └── app/
│       ├── main.py                  # FastAPI app
│       ├── routes/                  # REST + SSE endpoints
│       └── services/
│           ├── providers/           # Pluggable LLM backends
│           ├── session_store.py     # SQLite persistence
│           ├── event_store.py       # Event log for streaming replay
│           └── stream_broker.py     # In-memory SSE pub/sub
├── frontend/
│   └── src/
│       ├── components/chat/         # Chat UI, tool cards, agent status
│       ├── hooks/useEventStream.ts  # SSE subscription
│       └── contexts/               # Session state
├── hooks/                           # Claude Code hook scripts
└── scripts/                         # Setup and startup
```

## License

AGPL-3.0. See [LICENSE](LICENSE).
