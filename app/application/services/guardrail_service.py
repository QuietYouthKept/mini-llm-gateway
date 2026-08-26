"""Configurable input/output guardrails.

These are heuristic, config-driven policy hooks with audit output — NOT a claim
of complete protection against prompt injection or PII leakage.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from app.infrastructure.config.config_models import GuardrailConfig

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
_INJECTION_HINTS = (
    "ignore previous instructions",
    "ignore all previous",
    "you are now",
    "system prompt:",
)


@dataclass
class GuardrailDecision:
    allowed: bool
    action: str  # "allow" | "block"
    policy: str = ""
    reason: str = ""
    content: str | None = None  # modified content when truncated/redacted


class GuardrailService:
    def __init__(self, config: GuardrailConfig) -> None:
        self._config = config
        self._blocked_regex = [
            re.compile(p, re.IGNORECASE) for p in config.input_policy.blocked_regex
        ]
        self._blocked_terms = [t.lower() for t in config.output_policy.blocked_terms]
        policy = json.dumps(asdict(config.output_policy), sort_keys=True, ensure_ascii=False)
        self.policy_version = hashlib.sha256(policy.encode("utf-8")).hexdigest()[:16]

    def check_input(self, text: str) -> GuardrailDecision:
        if not self._config.enabled:
            return GuardrailDecision(allowed=True, action="allow")

        if text and len(text) > self._config.input_policy.max_chars:
            return GuardrailDecision(
                allowed=False,
                action="block",
                policy="input_policy",
                reason="input_too_long",
            )

        for rx in self._blocked_regex:
            if rx.search(text):
                return GuardrailDecision(
                    allowed=False,
                    action="block",
                    policy="input_policy",
                    reason=f"blocked_pattern:{rx.pattern}",
                )

        if self._config.input_policy.pii_detection and (
            _EMAIL_RE.search(text) or _PHONE_RE.search(text)
        ):
            return GuardrailDecision(
                allowed=False,
                action="block",
                policy="input_policy",
                reason="pii_detected",
            )

        if self._config.input_policy.prompt_injection:
            lowered = text.lower()
            if any(hint in lowered for hint in _INJECTION_HINTS):
                return GuardrailDecision(
                    allowed=False,
                    action="block",
                    policy="input_policy",
                    reason="prompt_injection_hint",
                )

        return GuardrailDecision(allowed=True, action="allow")

    def check_output(self, text: str) -> GuardrailDecision:
        if not self._config.enabled:
            return GuardrailDecision(allowed=True, action="allow")

        lowered = text.lower()
        for term in self._blocked_terms:
            if term.lower() in lowered:
                return GuardrailDecision(
                    allowed=False,
                    action="block",
                    policy="output_policy",
                    reason=f"blocked_term:{term}",
                )

        if text and len(text) > self._config.output_policy.max_chars:
            truncated = text[: self._config.output_policy.max_chars]
            return GuardrailDecision(
                allowed=True,
                action="allow",
                policy="output_policy",
                reason="output_truncated",
                content=truncated,
            )

        return GuardrailDecision(allowed=True, action="allow")
