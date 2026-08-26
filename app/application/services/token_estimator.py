"""Heuristic token estimation and cost calculation."""

from __future__ import annotations

import math

from app.domain.ports.provider_port import ChatMessage


class TokenEstimator:
    """Estimate token counts from raw text using a chars-per-token heuristic."""

    def __init__(
        self,
        chars_per_token: int = 4,
        min_tokens: int = 1,
        cost_per_1k_input_usd: float = 0.0,
        cost_per_1k_output_usd: float = 0.0,
    ) -> None:
        self._chars_per_token = max(1, chars_per_token)
        self._min_tokens = max(1, min_tokens)
        self._cost_in = cost_per_1k_input_usd
        self._cost_out = cost_per_1k_output_usd

    def estimate_text(self, text: str) -> int:
        if not text:
            return 0
        return max(self._min_tokens, math.ceil(len(text) / self._chars_per_token))

    def estimate_messages(self, messages: list[ChatMessage]) -> int:
        return sum(self.estimate_text(m.content) for m in messages)

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            (input_tokens / 1000.0) * self._cost_in
            + (output_tokens / 1000.0) * self._cost_out,
            6,
        )
