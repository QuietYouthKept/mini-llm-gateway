"""Deterministic OpenAI-compatible fault provider used by local experiments."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

from fastapi import FastAPI, Header, Response
from fastapi.responses import StreamingResponse

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions", response_model=None)
async def chat(payload: dict, x_fault_mode: str = Header(default="success")) -> Any:
    if payload.get("stream"):
        async def frames():
            if x_fault_mode == "timeout":
                await asyncio.sleep(1.0)
            frame = {
                "id": "synthetic-fault-provider-request",
                "model": "fault-fixture",
                "choices": [{"delta": {"content": "partial from fault fixture"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(frame)}\n\n"
            if x_fault_mode == "stream_then_error":
                await asyncio.sleep(0.02)
                yield "data: {malformed-json-frame}\n\n"
                return
            final = {
                "id": "synthetic-fault-provider-request",
                "model": "fault-fixture",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")
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
