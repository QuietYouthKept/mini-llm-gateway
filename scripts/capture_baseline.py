"""Capture a clean-checkout, commit-bound local verification baseline.

The script refuses to run from a dirty Git tree so results cannot accidentally
mix source revisions.  It writes only a new timestamped evidence directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _run(command: list[str], log_path: Path) -> dict[str, Any]:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    return {"command": command, "exit_code": result.returncode, "log": log_path.name}


def capture(output_root: Path) -> tuple[Path, dict[str, Any]]:
    if _git("status", "--porcelain"):
        raise RuntimeError("Refusing baseline capture from a dirty Git worktree")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    config_path = ROOT / "config" / "config.yaml"
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "commands": [],
    }
    commands = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "compileall", "-q", "app", "tests", "eval", "scripts"],
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "scripts/check_streaming_consistency.py"],
        [sys.executable, "scripts/secret_scan.py"],
        [sys.executable, "eval/run_eval.py"],
        [sys.executable, "eval/run_eval.py", "--cases", "eval/security_cases.yaml"],
        ["git", "diff", "--check"],
    ]
    for index, command in enumerate(commands, start=1):
        manifest["commands"].append(_run(command, run_dir / f"{index:02d}.log"))
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return run_dir, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "evidence" / "baseline",
        help="Directory that will contain a timestamped run folder.",
    )
    args = parser.parse_args()
    try:
        run_dir, manifest = capture(args.output_root)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Baseline capture failed: {exc}", file=sys.stderr)
        return 2
    failures = [entry for entry in manifest["commands"] if entry["exit_code"]]
    print(f"Baseline written to {run_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
