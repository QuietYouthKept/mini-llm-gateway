"""Provider domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderType(Enum):
    MOCK = "mock"
    FAKE_STATIC = "fake_static"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass
class ProviderBehavior:
    latency_ms: int = 100
    error_rate: float = 0.0
    timeout_ms: int = 1000
    default_response: str = ""


@dataclass
class ProviderConfig:
    provider_id: str = ""
    type: ProviderType = ProviderType.MOCK
    enabled: bool = True
    behavior: ProviderBehavior = field(default_factory=ProviderBehavior)


@dataclass
class ProviderAttempt:
    """Records the outcome of a single provider call attempt."""

    provider_id: str
    attempt_order: int
    status: str  # "success" | "timeout" | "error" | "bad_status" | "circuit_open"
    latency_ms: int = 0
    status_code: int | None = None
    error_code: str = ""
    error_message: str = ""
    retry_index: int = 0
    response: dict[str, Any] | None = None
