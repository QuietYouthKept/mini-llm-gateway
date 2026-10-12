from __future__ import annotations

import asyncio
import json
from collections import Counter

import pytest

import scripts.fault_provider_app as fault_provider


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_fault_provider_injects_status_and_retry_after(status: int, monkeypatch) -> None:
    monkeypatch.setattr(fault_provider, "_request_counts", Counter())

    response = await fault_provider.chat({}, x_fault_mode=str(status), x_retry_after="3")

    assert response.status_code == status
    assert response.headers.get("retry-after") == ("3" if status == 429 else None)
    assert (await fault_provider.stats()) == {"requests": 1, "modes": {str(status): 1}}


@pytest.mark.asyncio
async def test_three_chunk_fault_barrier_stalls_until_harness_cuts_tcp(monkeypatch) -> None:
    monkeypatch.setattr(fault_provider, "_request_counts", Counter())
    response = await fault_provider.chat({"stream": True}, x_fault_mode="stream_3_chunks_stall")
    iterator = response.body_iterator

    chunks = [await anext(iterator) for _ in range(3)]
    decoded = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]
    content = [item["choices"][0]["delta"]["content"] for item in decoded]
    assert content == ["fault-chunk-1", "fault-chunk-2", "fault-chunk-3"]

    pending = asyncio.create_task(anext(iterator))
    done, _ = await asyncio.wait({pending}, timeout=0.03)
    assert not done, "the provider must wait for the harness to inject its network fault"
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_usage", "done_count"),
    [
        ("stream_usage_missing", None, 1),
        (
            "stream_usage_invalid",
            {"prompt_tokens": -1, "completion_tokens": 4, "total_tokens": 3},
            1,
        ),
        (
            "stream_usage_conflicting",
            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 99},
            1,
        ),
        (
            "stream_duplicate_done",
            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            2,
        ),
        (
            "stream_missing_done",
            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            0,
        ),
    ],
)
async def test_usage_and_terminal_frame_faults_are_deterministic(
    mode: str, expected_usage: dict | None, done_count: int, monkeypatch
) -> None:
    monkeypatch.setattr(fault_provider, "_request_counts", Counter())
    response = await fault_provider.chat({"stream": True}, x_fault_mode=mode)
    frames = [frame async for frame in response.body_iterator]
    decoded = [
        json.loads(frame.removeprefix("data: ").strip())
        for frame in frames
        if frame.strip() != "data: [DONE]"
    ]
    final = next(item for item in decoded if item["choices"][0]["finish_reason"] == "stop")

    assert final.get("usage") == expected_usage
    assert sum(frame.strip() == "data: [DONE]" for frame in frames) == done_count
    assert (await fault_provider.stats())["modes"] == {mode: 1}
