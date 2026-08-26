"""Base class for mock providers."""

from __future__ import annotations

import asyncio
import math
import random

from app.domain.errors import (
    ProviderFailedError,
    ProviderTimeoutError,
)
from app.domain.models.provider import ProviderBehavior
from app.domain.ports.provider_port import (
    ChatRequest,
    ChatResponse,
    ProviderPort,
)


class BaseMockProvider(ProviderPort):
    """Shared logic for mock/fake providers.

    Subclasses override _build_response and optionally _should_error / _should_timeout.
    """

    def __init__(
        self,
        provider_id: str,
        provider_type: str,
        behavior: ProviderBehavior,
    ) -> None:
        self._provider_id = provider_id
        self._provider_type = provider_type
        self._behavior = behavior

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_type(self) -> str:
        return self._provider_type

    async def chat(self, request: ChatRequest) -> ChatResponse:
        await self._simulate_latency()

        if self._should_timeout():
            raise ProviderTimeoutError(provider_id=self._provider_id)

        if self._should_error():
            raise ProviderFailedError(
                provider_id=self._provider_id,
                reason="simulated error",
            )

        return self._build_response(request)

    # ── hooks for subclasses ──

    def _build_response(self, request: ChatRequest) -> ChatResponse:
        user_text = request.messages[-1].content if request.messages else ""
        content = self._bounded_content(
            f"[{self._provider_id}] {self._behavior.default_response}: {user_text}",
            request.max_tokens,
        )
        prompt_tokens = sum(math.ceil(len(message.content) / 4) for message in request.messages)
        completion_tokens = math.ceil(len(content) / 4) if content else 0
        return ChatResponse(
            content=content,
            provider_id=self._provider_id,
            model=self._provider_id,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    @staticmethod
    def _bounded_content(content: str, max_tokens: int) -> str:
        """Honor the mock provider's completion token envelope deterministically."""
        return content[: max(0, max_tokens) * 4]

    def _should_error(self) -> bool:
        return random.random() < self._behavior.error_rate

    def _should_timeout(self) -> bool:
        return False  # subclasses override

    async def _simulate_latency(self) -> None:
        delay_ms = self._behavior.latency_ms
        await asyncio.sleep(delay_ms / 1000.0)
