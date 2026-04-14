from __future__ import annotations

import logging
from typing import Optional

from app.services.providers.base import BaseProvider, ProviderInfo

logger = logging.getLogger(__name__)

_providers: dict[str, BaseProvider] = {}
_initialized = False


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    from app.services.providers.claude_code import ClaudeCodeProvider
    from app.services.providers.mlx_server import MLXServerProvider

    register("claude-code", ClaudeCodeProvider())
    register("mlx-server", MLXServerProvider())
    logger.info("Registered providers: %s", list(_providers.keys()))


def register(provider_id: str, provider: BaseProvider) -> None:
    _providers[provider_id] = provider


def get_provider(provider_id: str) -> Optional[BaseProvider]:
    _ensure_initialized()
    return _providers.get(provider_id)


def list_providers() -> list[ProviderInfo]:
    _ensure_initialized()
    return [p.info() for p in _providers.values()]


def get_provider_info(provider_id: str) -> Optional[ProviderInfo]:
    _ensure_initialized()
    p = _providers.get(provider_id)
    return p.info() if p else None


def all_providers() -> dict[str, BaseProvider]:
    _ensure_initialized()
    return dict(_providers)
