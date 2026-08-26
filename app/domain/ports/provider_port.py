"""Provider port — the abstract interface all providers must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class ChatRequest:
    profile: str = ""
    model: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    max_tokens: int = 512
    temperature: float = 0.0
    stream: bool = False


@dataclass
class ChatResponse:
    content: str
    provider_id: str
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class ProviderPort(ABC):
    """Contract that every provider adapter must fulfill."""

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Send a chat request to the provider and return the response.

        Must raise domain errors (ProviderTimeoutError, ProviderFailedError,
        ProviderBadStatusError) so the fallback engine can react.
        """
        ...

    @property
    @abstractmethod
    def provider_id(self) -> str:
        ...

    @property
    @abstractmethod
    def provider_type(self) -> str:
        ...
