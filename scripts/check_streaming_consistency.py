"""Fail CI when Streaming claims, config, adapter, and tests drift apart."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: Path, fragment: str) -> None:
    if fragment not in path.read_text(encoding="utf-8"):
        raise SystemExit(
            f"Streaming consistency check failed: {path.relative_to(ROOT)} lacks {fragment!r}"
        )


def forbid(path: Path, fragment: str) -> None:
    if fragment in path.read_text(encoding="utf-8"):
        raise SystemExit(
            f"Streaming consistency check failed: {path.relative_to(ROOT)} contains {fragment!r}"
        )


def main() -> int:
    config = ROOT / "config" / "config.yaml"
    readme = ROOT / "README.md"
    adapter = ROOT / "app" / "infrastructure" / "providers" / "openai_compatible.py"
    api_test = ROOT / "tests" / "integration" / "test_chat_api.py"

    require(config, "enabled: true")
    require(config, "output_guardrail_mode: incremental")
    forbid(config, "supports_streaming: false")
    require(readme, "event: message")
    forbid(readme, "Streaming** is deliberately rejected")
    require(adapter, '"stream": True')
    require(api_test, "test_streaming_returns_sse_and_audits_completion")
    forbid(api_test, "test_streaming_rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
