"""Deterministic OpenAI-compatible fault provider used by local experiments."""

from __future__ import annotations

import asyncio
import json
import math
from collections import Counter
from typing import Any

from fastapi import FastAPI, Header, Response
from fastapi.responses import StreamingResponse

app = FastAPI()
_request_counts: Counter[str] = Counter()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
async def stats() -> dict[str, Any]:
    """Expose bounded per-process counts without request IDs or prompt data."""
    return {
        "requests": sum(_request_counts.values()),
        "modes": dict(sorted(_request_counts.items())),
    }


@app.post("/v1/chat/completions", response_model=None)
async def chat(
    payload: dict,
    x_fault_mode: str = Header(default="success"),
    x_retry_after: str = Header(default="1"),
) -> Any:
    mode = x_fault_mode.strip().lower()
    _request_counts[mode] += 1

    if mode in {"429", "500", "502", "503"}:
        headers = {"Retry-After": x_retry_after} if mode == "429" else None
        return Response(status_code=int(mode), content="injected provider status", headers=headers)

    if payload.get("stream"):
        async def frames():
            if mode == "timeout":
                await asyncio.sleep(1.0)
            if mode == "first_chunk_delay":
                await asyncio.sleep(0.25)
            if mode in {"stream_3_chunks_stall", "stream_3_chunks_reset_trigger"}:
                for index in range(1, 4):
                    frame = {
                        "id": "synthetic-fault-provider-request",
                        "model": "fault-fixture",
                        "choices": [
                            {"delta": {"content": f"fault-chunk-{index}"}, "finish_reason": None}
                        ],
                    }
                    yield f"data: {json.dumps(frame)}\n\n"
                # The test harness activates a TCP reset toxic only after it has
                # observed all three chunks at the downstream client. Toxiproxy's
                # reset_peer toxic needs another upstream frame to trigger, so
                # this fourth frame is deliberately delayed and must be dropped.
                if mode == "stream_3_chunks_reset_trigger":
                    await asyncio.sleep(0.25)
                    trigger = {
                        "id": "synthetic-fault-provider-request",
                        "model": "fault-fixture",
                        "choices": [
                            {"delta": {"content": "must-not-reach-client"}, "finish_reason": None}
                        ],
                    }
                    yield f"data: {json.dumps(trigger)}\n\n"
                await asyncio.Event().wait()
            if mode == "stream_half_frame":
                yield 'data: {"choices":[{"delta":{"content":"partial"'
                return
            frame = {
                "id": "synthetic-fault-provider-request",
                "model": "fault-fixture",
                "choices": [{"delta": {"content": "partial from fault fixture"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(frame)}\n\n"
            if mode == "stream_then_error":
                await asyncio.sleep(0.02)
                yield "data: {malformed-json-frame}\n\n"
                return
            final = {
                "id": "synthetic-fault-provider-request",
                "model": "fault-fixture",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
            }
            if mode not in {"stream_usage_missing"}:
                final["usage"] = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
            if mode == "stream_usage_invalid":
                final["usage"] = {"prompt_tokens": -1, "completion_tokens": 4, "total_tokens": 3}
            elif mode == "stream_usage_conflicting":
                final["usage"] = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 99}
            yield f"data: {json.dumps(final)}\n\n"
            if mode != "stream_missing_done":
                yield "data: [DONE]\n\n"
            if mode == "stream_duplicate_done":
                yield "data: [DONE]\n\n"
            if mode == "stream_missing_done":
                return

        return StreamingResponse(frames(), media_type="text/event-stream")
    if mode == "timeout":
        await asyncio.sleep(2.0)
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
