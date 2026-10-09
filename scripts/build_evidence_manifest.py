"""Create a SHA-256 manifest for public, sanitized CI evidence files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command(*args: str) -> str:
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    evidence_dir = args.directory.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    statuses = evidence_dir / "status"
    results: dict[str, Any] = {}
    if statuses.exists():
        for path in sorted(statuses.glob("*.exitcode")):
            try:
                results[path.stem] = {"exit_code": int(path.read_text(encoding="utf-8").strip())}
            except ValueError:
                results[path.stem] = {"exit_code": None, "status": "invalid_status_file"}
    files = [path for path in evidence_dir.rglob("*") if path.is_file() and path.name != "manifest.json"]
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": command("git", "rev-parse", "HEAD"),
        "git_tree": command("git", "rev-parse", "HEAD^{tree}"),
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
        "workflow": os.getenv("GITHUB_WORKFLOW", "local"),
        "python": sys.version,
        "platform": platform.platform(),
        "pip_version": command(sys.executable, "-m", "pip", "--version"),
        "dependency_lock_sha256": sha256(ROOT / "uv.lock"),
        "config_sha256": sha256(ROOT / "config" / "config.yaml"),
        "results": results,
        "files": [
            {
                "path": path.relative_to(evidence_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(files)
        ],
    }
    output = evidence_dir / "manifest.json"
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (evidence_dir / "manifest.sha256").write_text(
        f"{sha256(output)}  manifest.json\n", encoding="utf-8"
    )
    print(f"Evidence manifest written: {output}")
    print(f"Evidence files hashed: {len(files)}")
    print(f"Git SHA: {manifest['git_sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
