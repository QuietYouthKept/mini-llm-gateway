"""One-command local release gate using the active Python interpreter."""

from __future__ import annotations

import subprocess
import sys

COMMANDS = [
    [sys.executable, "-m", "ruff", "check", "."],
    [sys.executable, "-m", "compileall", "-q", "app", "tests", "scripts", "eval"],
    [sys.executable, "-m", "pytest", "-q"],
    [sys.executable, "eval/run_eval.py"],
    [sys.executable, "eval/run_eval.py", "--cases", "eval/security_cases.yaml"],
]


def main() -> int:
    for command in COMMANDS:
        result = subprocess.run(command, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
