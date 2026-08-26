"""Tests for the guardrail service."""

from __future__ import annotations

from app.application.services.guardrail_service import GuardrailService
from app.infrastructure.config.config_models import (
    GuardrailConfig,
    InputPolicyConfig,
    OutputPolicyConfig,
)


def make_guardrails() -> GuardrailConfig:
    return GuardrailConfig(
        enabled=True,
        input_policy=InputPolicyConfig(
            max_chars=100,
            blocked_regex=["drop\\s+table", "blockme"],
        ),
        output_policy=OutputPolicyConfig(max_chars=100, blocked_terms=["secret"]),
    )


def test_blocks_matching_regex() -> None:
    svc = GuardrailService(make_guardrails())
    decision = svc.check_input("please drop   table now")
    assert decision.allowed is False
    assert decision.reason == "blocked_pattern:drop\\s+table"


def test_blocks_literal_pattern() -> None:
    svc = GuardrailService(make_guardrails())
    decision = svc.check_input("this has blockme in it")
    assert decision.allowed is False


def test_blocks_too_long_input() -> None:
    svc = GuardrailService(make_guardrails())
    decision = svc.check_input("x" * 101)
    assert decision.allowed is False
    assert decision.reason == "input_too_long"


def test_allows_clean_input() -> None:
    svc = GuardrailService(make_guardrails())
    decision = svc.check_input("hello world")
    assert decision.allowed is True


def test_output_blocks_term() -> None:
    svc = GuardrailService(make_guardrails())
    decision = svc.check_output("the secret is out")
    assert decision.allowed is False
    assert decision.reason == "blocked_term:secret"


def test_output_truncates_long_text() -> None:
    svc = GuardrailService(make_guardrails())
    decision = svc.check_output("x" * 150)
    assert decision.allowed is True
    assert decision.content is not None
    assert len(decision.content) == 100


def test_disabled_guardrails_allow_all() -> None:
    config = make_guardrails()
    config.enabled = False
    svc = GuardrailService(config)
    assert svc.check_input("blockme").allowed is True
