"""Deterministic OpenAI-compatible fault provider used by local experiments."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from fastapi import FastAPI, Header, Response

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions", response_model=None)
async def chat(payload: dict, x_fault_mode: str = Header(default="success")) -> Any:
    if x_fault_mode == "timeout":
        await asyncio.sleep(2.0)
    if x_fault_mode == "500":
        return Response(status_code=500, content="injected provider failure")
    messages = payload.get("messages") or []
    prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
    max_tokens = max(0, int(payload.get("max_tokens", 32)))
    content = "deterministic local provider response"[: max_tokens * 4]
    prompt_tokens = math.ceil(prompt_chars / 4) if prompt_chars else 0
    completion_tokens = math.ceil(len(content) / 4) if content else 0
    return {
        "model": payload.get("model") or "fault-fixture",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
