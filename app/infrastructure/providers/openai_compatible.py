"""Real OpenAI-compatible HTTP provider adapter.

Talks to any OpenAI-style /chat/completions endpoint (OpenAI, DeepSeek, Qwen,
or a self-hosted vLLM/Ollama server). Maps transport errors into the gateway's
domain errors so the fallback/retry/circuit machinery can react uniformly.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.domain.errors import ProviderBadStatusError, ProviderFailedError, ProviderTimeoutError
from app.domain.models.provider import ProviderBehavior
from app.domain.ports.provider_port import (
    ChatRequest,
    ChatResponse,
    ProviderChunk,
    ProviderPort,
)
from app.infrastructure.config.config_models import HTTPProviderConfig


class OpenAICompatibleProvider(ProviderPort):
    def __init__(
        self,
        provider_id: str,
        http: HTTPProviderConfig,
        behavior: ProviderBehavior | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._http = http
        self._behavior = behavior or ProviderBehavior()
        self._api_key = self._resolve_api_key(http)
        timeout_ms = http.timeout_ms or self._behavior.timeout_ms or 15000
        self._timeout = httpx.Timeout(timeout_ms / 1000.0)
        self._owns_client = client is None
        # Provider traffic must not silently inherit workstation proxy state.
        self._client = client or httpx.AsyncClient(timeout=self._timeout, trust_env=False)

    @staticmethod
    def _resolve_api_key(http: HTTPProviderConfig) -> str:
        if http.api_key_env:
            return os.environ.get(http.api_key_env, "")
        return http.api_key

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_type(self) -> str:
        return "openai_compatible"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        url = self._http.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        headers.update(self._http.headers)

        model = request.model or self._http.model
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": False,
        }

        try:
            response = await self._client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(provider_id=self._provider_id) from exc
        except httpx.RequestError as exc:
            raise ProviderFailedError(provider_id=self._provider_id, reason=str(exc)) from exc

        if response.status_code != 200:
            raise ProviderBadStatusError(
                provider_id=self._provider_id, status_code=response.status_code
            )

        return self._parse_response(response.json(), response.headers)

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ProviderChunk]:
        """Read an upstream OpenAI-style SSE response as it arrives.

        Holding the HTTP context manager across iteration makes downstream
        cancellation close the upstream response rather than buffering it.
        """
        url = self._http.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        headers.update(self._http.headers)
        payload = {
            "model": request.model or self._http.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            async with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=self._timeout
            ) as response:
                if response.status_code != 200:
                    raise ProviderBadStatusError(
                        provider_id=self._provider_id, status_code=response.status_code
                    )
                provider_request_id = str(
                    response.headers.get("x-request-id") or response.headers.get("request-id") or ""
                )
                index = 0
                seen_done = False
                async for line in response.aiter_lines():
                    if not line or line.startswith(":") or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        if not seen_done:
                            seen_done = True
                            yield ProviderChunk(
                                finish_reason="stop",
                                provider_request_id=provider_request_id,
                                index=index,
                                received_at_ms=int(time.monotonic() * 1000),
                            )
                        continue
                    try:
                        data = json.loads(raw)
                        choices = data.get("choices", [])
                        choice = choices[0] if choices else {}
                        delta = choice.get("delta", {}).get("content") or ""
                        finish_reason = choice.get("finish_reason")
                        raw_usage = data.get("usage")
                    except (AttributeError, TypeError, ValueError) as exc:
                        raise ProviderFailedError(
                            provider_id=self._provider_id, reason="malformed streaming SSE frame"
                        ) from exc
                    usage = None
                    if isinstance(raw_usage, dict):
                        usage = {
                            "prompt_tokens": int(raw_usage.get("prompt_tokens", 0)),
                            "completion_tokens": int(raw_usage.get("completion_tokens", 0)),
                            "total_tokens": int(raw_usage.get("total_tokens", 0)),
                        }
                    yield ProviderChunk(
                        delta=delta,
                        finish_reason=finish_reason,
                        provider_request_id=str(data.get("id") or provider_request_id),
                        usage=usage,
                        index=index,
                        received_at_ms=int(time.monotonic() * 1000),
                    )
                    if finish_reason is not None:
                        seen_done = True
                    index += 1
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(provider_id=self._provider_id) from exc
        except httpx.RequestError as exc:
            raise ProviderFailedError(provider_id=self._provider_id, reason=str(exc)) from exc

    def _parse_response(self, data: dict[str, Any], headers: httpx.Headers) -> ChatResponse:
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data.get("usage", {})
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderFailedError(
                provider_id=self._provider_id, reason="malformed response"
            ) from exc

        return ChatResponse(
            content=content,
            provider_id=self._provider_id,
            model=data.get("model", self._http.model),
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            },
            metadata={
                "provider_request_id": str(
                    headers.get("x-request-id") or headers.get("request-id") or data.get("id") or ""
                )
            },
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
