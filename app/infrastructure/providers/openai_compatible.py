"""Real OpenAI-compatible HTTP provider adapter.

Talks to any OpenAI-style /chat/completions endpoint (OpenAI, DeepSeek, Qwen,
or a self-hosted vLLM/Ollama server). Maps transport errors into the gateway's
domain errors so the fallback/retry/circuit machinery can react uniformly.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.domain.errors import ProviderBadStatusError, ProviderFailedError, ProviderTimeoutError
from app.domain.models.provider import ProviderBehavior
from app.domain.ports.provider_port import ChatRequest, ChatResponse, ProviderPort
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
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": False,
        }

        try:
            response = await self._client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(provider_id=self._provider_id) from exc
        except httpx.RequestError as exc:
            raise ProviderFailedError(
                provider_id=self._provider_id, reason=str(exc)
            ) from exc

        if response.status_code != 200:
            raise ProviderBadStatusError(
                provider_id=self._provider_id, status_code=response.status_code
            )

        return self._parse_response(response.json())

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
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
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
