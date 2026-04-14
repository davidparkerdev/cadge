# Contributing

Contributions are welcome. Here's how to get started.

## Setup

1. Fork and clone the repo
2. Follow the [Quick start](README.md#quick-start) to get running locally
3. Create a branch for your work

## Guidelines

- Keep changes focused. One PR per feature or fix.
- The architecture is SSE-based streaming. No polling, no DB polling, no race condition workarounds. If something isn't working, fix the pipeline.
- Run the backend tests before submitting: `cd backend && pytest`
- Frontend should build clean: `cd frontend && npm run build`

## Adding a provider

The most useful contributions are new LLM provider integrations. See `backend/app/services/providers/base.py` for the interface and the existing Claude Code / MLX Server providers as reference.

## License

By contributing, you agree that your contributions will be licensed under AGPL-3.0.
