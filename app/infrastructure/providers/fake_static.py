"""fake_static — always-available fallback provider with a static response."""

from __future__ import annotations

import math

from app.domain.models.provider import ProviderBehavior, ProviderType
from app.domain.ports.provider_port import ChatRequest, ChatResponse
from app.infrastructure.providers.base import BaseMockProvider


class FakeStaticProvider(BaseMockProvider):
    def __init__(self, behavior: ProviderBehavior | None = None) -> None:
        super().__init__(
            provider_id="fake_static",
            provider_type=ProviderType.FAKE_STATIC.value,
            behavior=behavior
            or ProviderBehavior(
                latency_ms=20,
                error_rate=0.0,
                timeout_ms=1000,
                default_response="safe fallback response from fake_static",
            ),
        )

    def _should_error(self) -> bool:
        # fake_static never errors
        return False

    def _should_timeout(self) -> bool:
        # fake_static never times out
        return False

    def _build_response(self, request: ChatRequest) -> ChatResponse:
        user_text = request.messages[-1].content if request.messages else ""
        content = self._bounded_content(
            f"[fake_static] I'm a static fallback. You said: {user_text}",
            request.max_tokens,
        )
        prompt_tokens = sum(math.ceil(len(message.content) / 4) for message in request.messages)
        completion_tokens = math.ceil(len(content) / 4) if content else 0
        return ChatResponse(
            content=content,
            provider_id=self._provider_id,
            model="fake_static",
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )
