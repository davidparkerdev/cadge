"""Provider-agnostic message runner.

Delegates to the appropriate provider based on the session's provider_id.
Maintains backward compatibility with the original API surface used by
routes and main.py.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.providers.registry import get_provider, all_providers
from app.services.session_store import get_session

logger = logging.getLogger(__name__)

_active_processes: dict[str, Optional[object]] = {}


def active_session_count() -> int:
    return sum(p.active_count() for p in all_providers().values())


def is_session_streaming(session_id: str) -> bool:
    for provider in all_providers().values():
        if provider.is_streaming(session_id):
            return True
    return False


async def send_message(
    session_id: str,
    prompt: str,
    images: Optional[list[str]] = None,
) -> None:
    session = await get_session(session_id)
    if not session:
        logger.error("send_message called for unknown session %s", session_id)
        return

    provider_id = session.get("provider_id", "claude-code")
    provider = get_provider(provider_id)
    if not provider:
        logger.error("Unknown provider %s for session %s", provider_id, session_id)
        return

    await provider.send_message(session_id, prompt, images)


async def cancel_session(session_id: str) -> bool:
    for provider in all_providers().values():
        if provider.is_streaming(session_id):
            return await provider.cancel(session_id)
    return False


def cleanup_session_resources(session_id: str) -> None:
    for provider in all_providers().values():
        provider.cleanup_session(session_id)
