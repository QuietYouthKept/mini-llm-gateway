"""Fail when tracked source contains a likely live credential.

The scanner deliberately reports only a path and line number.  It never echoes
the matched text, so a failed CI log does not become another disclosure vector.
It is a lightweight hygiene gate, not a replacement for repository hosting
secret scanning or a managed secret store.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
)


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT, text=False
    )
    return [ROOT / item.decode("utf-8") for item in output.split(b"\0") if item]


def main() -> int:
    matches: list[str] = []
    for path in tracked_files():
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if any(pattern.search(line) for pattern in PATTERNS):
                matches.append(f"{path.relative_to(ROOT)}:{line_number}")
    if matches:
        print("Potential credential material detected (content intentionally redacted):")
        print("\n".join(matches))
        return 1
    print("Secret scan passed: no high-confidence credential patterns in tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
