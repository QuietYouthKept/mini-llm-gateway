"""Failure replay / routing regression tool.

Re-runs a historical gateway request against the CURRENT config and compares
the routing decision (selected provider, fallback, attempt chain) with what was
recorded. Exits 0 on PASS, 1 on REGRESSION.

    make replay REQUEST_ID=xxx
    # or: python scripts/replay_request.py --request-id xxx
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile

from app.core.startup import bootstrap
from app.domain.ports.provider_port import ChatMessage, ChatRequest
from app.infrastructure.persistence.sqlite.repositories import RequestLogRepository

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _attempt_signature(attempts: list[dict]) -> list[tuple]:
    return [
        (a.get("provider_id"), a.get("status"), a.get("retry_index", 0))
        for a in attempts
    ]


def _rebuild_request(data: dict) -> ChatRequest:
    payload = data.get("replay_payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    messages = [
        ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
        for m in payload.get("messages", [])
    ]
    return ChatRequest(
        profile=payload.get("profile", ""),
        model=payload.get("model", ""),
        messages=messages,
        max_tokens=payload.get("max_tokens", 512),
        temperature=payload.get("temperature", 0.0),
        stream=payload.get("stream", False),
    )


async def _replay(
    config_path: str,
    db_path: str,
    request_id: str,
    mode: str = "offline",
) -> tuple[dict, dict]:
    original = RequestLogRepository(db_path).get_request(request_id)
    if original is None:
        raise SystemExit(f"request '{request_id}' not found in {db_path}")
    if not original.get("replay_payload"):
        raise SystemExit(
            f"request '{request_id}' has no replay payload (was it logged before v0.2.0?)"
        )

    request = _rebuild_request(original)
    profile_id = original.get("model_profile") or request.profile or ""

    with tempfile.TemporaryDirectory() as tmp:
        container = bootstrap(
            config_path=config_path, database_path=os.path.join(tmp, "replay.db")
        )
        try:
            current = await container.chat_service.replay(
                request,
                profile_id,
                recorded_attempts=original.get("attempts", []),
                mode=mode,
            )
        finally:
            await container.close()

    return original, current


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay a historical request and detect routing regressions."
    )
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--db", default=os.path.join(BASE_DIR, "data", "gateway.db"))
    parser.add_argument("--config", default=os.path.join(BASE_DIR, "config", "config.yaml"))
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help="offline never calls providers; live requires replay.allow_live=true",
    )
    args = parser.parse_args()

    if args.mode == "live":
        print("WARNING: live replay may call external providers and incur cost", file=sys.stderr)
    original, current = asyncio.run(_replay(args.config, args.db, args.request_id, args.mode))

    old_provider = original.get("selected_provider")
    new_provider = current["selected_provider"]
    old_fallback = bool(original.get("fallback_used"))
    new_fallback = current["fallback_used"]
    old_attempts = _attempt_signature(original.get("attempts", []))
    new_attempts = _attempt_signature(current["attempts"])

    changed = (
        old_provider != new_provider
        or old_fallback != new_fallback
        or old_attempts != new_attempts
    )

    print("Replay result: " + ("REGRESSION" if changed else "PASS"))
    print()
    print("Original:")
    print(f"  profile: {original.get('model_profile')}")
    print(f"  selected_provider: {old_provider}")
    print(f"  fallback_used: {old_fallback}")
    print(f"  attempts: {old_attempts}")
    print()
    print("Current:")
    print(f"  profile: {current['profile']}")
    print(f"  selected_provider: {new_provider}")
    print(f"  fallback_used: {new_fallback}")
    print(f"  attempts: {new_attempts}")
    print()
    print("Decision changed:", changed)

    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
