from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderModel:
    id: str
    name: str
    context_length: Optional[int] = None
    owned_by: Optional[str] = None


@dataclass
class ProviderInfo:
    id: str
    name: str
    description: str
    supports_tools: bool = False
    supports_thinking: bool = False
    supports_images: bool = False
    supports_agents: bool = False
    requires_api_key: bool = False
    default_model: Optional[str] = None
    config: dict = field(default_factory=dict)


class BaseProvider(abc.ABC):

    @abc.abstractmethod
    def info(self) -> ProviderInfo:
        ...

    @abc.abstractmethod
    async def send_message(
        self,
        session_id: str,
        prompt: str,
        images: Optional[list[str]] = None,
    ) -> None:
        ...

    @abc.abstractmethod
    async def cancel(self, session_id: str) -> bool:
        ...

    @abc.abstractmethod
    async def list_models(self) -> list[ProviderModel]:
        ...

    @abc.abstractmethod
    async def check_status(self) -> dict:
        ...

    @abc.abstractmethod
    def is_streaming(self, session_id: str) -> bool:
        ...

    @abc.abstractmethod
    def active_count(self) -> int:
        ...

    def cleanup_session(self, session_id: str) -> None:
        pass
