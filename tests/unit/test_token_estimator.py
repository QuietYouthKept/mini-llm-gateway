"""Tests for heuristic token estimation and cost."""

from __future__ import annotations

from app.application.services.token_estimator import TokenEstimator
from app.domain.ports.provider_port import ChatMessage


def test_estimate_uses_chars_per_token() -> None:
    est = TokenEstimator(chars_per_token=4, min_tokens=1)
    assert est.estimate_text("abcd") == 1
    assert est.estimate_text("abcdefgh") == 2


def test_estimate_empty_is_zero() -> None:
    est = TokenEstimator(chars_per_token=4, min_tokens=1)
    assert est.estimate_text("") == 0


def test_estimate_respects_min_tokens() -> None:
    est = TokenEstimator(chars_per_token=4, min_tokens=1)
    assert est.estimate_text("x") == 1


def test_estimate_messages_sums_content() -> None:
    est = TokenEstimator(chars_per_token=4, min_tokens=1)
    messages = [
        ChatMessage(role="system", content="abcd"),
        ChatMessage(role="user", content="efgh"),
    ]
    assert est.estimate_messages(messages) == 2


def test_cost_calculation() -> None:
    est = TokenEstimator(cost_per_1k_input_usd=0.01, cost_per_1k_output_usd=0.02)
    cost = est.cost_usd(1000, 500)
    assert cost == 0.01 + 0.01  # 1k input = $0.01, 500 output = $0.01
