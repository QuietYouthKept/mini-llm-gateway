"""Chat data-plane endpoints: /v1/chat and /v1/chat/completions."""

from __future__ import annotations

import json
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.container import AppContainer
from app.domain.ports.provider_port import ChatMessage, ChatRequest
from app.infrastructure.config.config_models import ClientConfig
from app.interfaces.http.dependencies.auth import require_api_key
from app.interfaces.http.dependencies.container import get_container
from app.interfaces.http.schemas.chat import (
    AttemptOut,
    ChatCompletionOut,
    ChatCompletionsRequestIn,
    ChatRequestIn,
    ChatResponseOut,
    CompletionChoice,
    CompletionMessage,
    CompletionUsage,
)

router = APIRouter(prefix="/v1", tags=["chat"])


def _sse(event: str, data: dict[str, Any]) -> str:
    """Encode a single SSE event without allowing payload line injection."""
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def _stream_response(session) -> StreamingResponse:  # noqa: ANN001
    async def events():
        async for item in session.events:
            yield _sse(item.event, item.data)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _to_domain_request(
    profile: str, model: str, messages: list, max_tokens: int, temperature: float, stream: bool
) -> ChatRequest:
    return ChatRequest(
        profile=profile,
        model=model,
        messages=[ChatMessage(role=m.role, content=m.content) for m in messages],
        max_tokens=max_tokens,
        temperature=temperature,
        stream=stream,
    )


@router.post("/chat", response_model=ChatResponseOut)
async def chat(
    payload: ChatRequestIn,
    client: Annotated[ClientConfig, Depends(require_api_key)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> ChatResponseOut | StreamingResponse:
    request = _to_domain_request(
        payload.profile or "",
        payload.model or "",
        payload.messages,
        payload.max_tokens,
        payload.temperature,
        payload.stream,
    )
    if payload.stream:
        session = await container.chat_service.start_stream(request, client, endpoint="/v1/chat")
        return _stream_response(session)
    outcome = await container.chat_service.chat(request, client, endpoint="/v1/chat")
    return ChatResponseOut(
        request_id=outcome.request_id,
        content=outcome.content,
        provider=outcome.provider_id,
        model=outcome.model,
        fallback_used=outcome.fallback_used,
        attempts=[
            AttemptOut(
                provider_id=a.provider_id,
                attempt_order=a.attempt_order,
                retry_index=a.retry_index,
                status=a.status,
                latency_ms=a.latency_ms,
                error_code=a.error_code,
                error_message=a.error_message,
                provider_request_id=a.provider_request_id or None,
            )
            for a in outcome.attempts
        ],
        decision_trace=outcome.decision_trace,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        estimated_tokens=outcome.estimated_tokens,
        estimated_input_tokens=outcome.estimated_input_tokens,
        estimated_output_tokens=outcome.estimated_output_tokens,
        actual_input_tokens=outcome.actual_input_tokens,
        actual_output_tokens=outcome.actual_output_tokens,
        usage_source=outcome.usage_source,
        estimated_cost_usd=outcome.estimated_cost_usd,
        cost_saved_usd=outcome.cost_saved_usd,
        budget_before=outcome.budget_before,
        budget_after=outcome.budget_after,
        cache_hit=outcome.cache_hit,
        cache_key=outcome.cache_key,
        duration_ms=outcome.duration_ms,
    )


@router.post("/chat/completions", response_model=ChatCompletionOut)
async def chat_completions(
    payload: ChatCompletionsRequestIn,
    client: Annotated[ClientConfig, Depends(require_api_key)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> ChatCompletionOut | StreamingResponse:
    request = _to_domain_request(
        payload.model or "",
        payload.model or "",
        payload.messages,
        payload.max_tokens,
        payload.temperature,
        payload.stream,
    )
    if payload.stream:
        session = await container.chat_service.start_stream(
            request, client, endpoint="/v1/chat/completions"
        )
        return _stream_response(session)
    outcome = await container.chat_service.chat(request, client, endpoint="/v1/chat/completions")
    resolved_model = payload.model or container.config.gateway.default_profile
    return ChatCompletionOut(
        id=outcome.request_id,
        created=int(time.time()),
        model=resolved_model,
        choices=[CompletionChoice(message=CompletionMessage(content=outcome.content))],
        usage=CompletionUsage(
            prompt_tokens=outcome.input_tokens,
            completion_tokens=outcome.output_tokens,
            total_tokens=outcome.estimated_tokens,
        ),
    )
