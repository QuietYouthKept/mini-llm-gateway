"""Pydantic schemas for chat endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class MessageIn(BaseModel):
    role: str = "user"
    content: str


class ChatRequestIn(BaseModel):
    profile: str | None = None
    model: str | None = None
    messages: list[MessageIn]
    max_tokens: int = 512
    temperature: float = 0.0
    stream: bool = False


class ChatCompletionsRequestIn(BaseModel):
    """OpenAI-compatible request body; 'model' is a logical profile name."""

    model: str = ""
    messages: list[MessageIn]
    max_tokens: int = 512
    temperature: float = 0.0
    stream: bool = False

    model_config = {"extra": "ignore"}


# ── verbose (debug) response for /v1/chat ──


class AttemptOut(BaseModel):
    provider_id: str
    attempt_order: int
    retry_index: int = 0
    status: str
    latency_ms: int = 0
    error_code: str = ""
    error_message: str = ""
    provider_request_id: str | None = None


class ChatResponseOut(BaseModel):
    request_id: str
    content: str
    provider: str
    model: str
    fallback_used: bool
    attempts: list[AttemptOut]
    decision_trace: list[dict] = []
    input_tokens: int
    output_tokens: int
    estimated_tokens: int
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    usage_source: str = "estimated"
    estimated_cost_usd: float
    cost_saved_usd: float = 0.0
    budget_before: int | None
    budget_after: int | None
    cache_hit: bool = False
    cache_key: str = ""
    duration_ms: int


# ── OpenAI-compatible response for /v1/chat/completions ──


class CompletionMessage(BaseModel):
    role: str = "assistant"
    content: str


class CompletionChoice(BaseModel):
    index: int = 0
    message: CompletionMessage
    finish_reason: str = "stop"


class CompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionOut(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[CompletionChoice]
    usage: CompletionUsage
