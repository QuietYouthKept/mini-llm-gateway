"""Explainable routing decision trace.

A decision trace is an ordered list of steps recording WHY the gateway made
each choice: which profile was resolved, whether rate/budget/guardrails passed,
why a provider was selected, skipped, retried, or fell back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecisionStep:
    step: str
    provider: str = ""
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"step": self.step}
        if self.provider:
            result["provider"] = self.provider
        if self.reason:
            result["reason"] = self.reason
        result.update(self.meta)
        return result


DecisionTrace = list[DecisionStep]
