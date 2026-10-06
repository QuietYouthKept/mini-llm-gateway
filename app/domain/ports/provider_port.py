"""Provider port — the abstract interface all providers must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
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
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ProviderChunk:
    """One increment received from a provider streaming response.

    ``usage`` is optional because OpenAI-compatible providers commonly include
    it only in their final SSE frame (and some omit it altogether).
    """

    delta: str = ""
    finish_reason: str | None = None
    provider_request_id: str = ""
    usage: dict[str, int] | None = None
    index: int = 0
    received_at_ms: int = 0


class ProviderPort(ABC):
    """Contract that every provider adapter must fulfill."""

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Send a chat request to the provider and return the response.

        Must raise domain errors (ProviderTimeoutError, ProviderFailedError,
        ProviderBadStatusError) so the fallback engine can react.
        """
        ...

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ProviderChunk]:
        """Stream provider deltas without buffering the full response.

        This intentionally remains optional for legacy provider adapters: they
        continue to support non-streaming calls, while the gateway reports a
        controlled stream error if selected for an SSE request.
        """
        raise NotImplementedError(f"Provider '{self.provider_id}' does not support streaming")
        yield ProviderChunk()  # pragma: no cover - makes this an async iterator

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @property
    @abstractmethod
    def provider_type(self) -> str: ...
