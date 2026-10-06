"""Run a reproducible stub-load matrix by delegating each cell to run_experiment.

The matrix writer never overwrites evidence: every cell gets a deterministic,
unique run ID beneath its parent matrix directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def csv_ints(value: str) -> list[int]:
    try:
        items = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a comma-separated integer list") from exc
    if not items or any(item <= 0 for item in items):
        raise argparse.ArgumentTypeError("values must be positive")
    return items


def csv_floats(value: str) -> list[float]:
    try:
        items = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a comma-separated number list") from exc
    if not items or any(item < 0 or item > 1 for item in items):
        raise argparse.ArgumentTypeError("cache ratios must be in [0, 1]")
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="demo-key")
    parser.add_argument("--profile", default="fast-chat")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "config.yaml")
    parser.add_argument("--output-root", type=Path, default=ROOT / "evidence" / "load")
    parser.add_argument("--matrix-id")
    parser.add_argument("--requests-per-cell", type=int, default=500)
    parser.add_argument("--concurrency", type=csv_ints, default=[1, 8, 32, 64])
    parser.add_argument("--cache-ratio", type=csv_floats, default=[0.0, 0.9])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--shape", choices=("constant", "ramp", "spike", "soak"), default="spike")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.requests_per_cell <= 0 or args.repetitions <= 0:
        parser.error("requests-per-cell and repetitions must be positive")
    return args


def main() -> int:
    args = parse_args()
    matrix_id = args.matrix_id or datetime.now(UTC).strftime("stub-matrix-%Y%m%dT%H%M%SZ")
    matrix_dir = args.output_root / matrix_id
    if matrix_dir.exists():
        raise SystemExit(f"Evidence directory already exists: {matrix_dir}")
    matrix_dir.mkdir(parents=True)
    results: list[dict[str, object]] = []

    for concurrency in args.concurrency:
        for cache_ratio in args.cache_ratio:
            for repetition in range(1, args.repetitions + 1):
                run_id = f"{matrix_id}-c{concurrency}-cache{cache_ratio:g}-r{repetition}"
                command = [
                    sys.executable,
                    str(ROOT / "scripts" / "run_experiment.py"),
                    "--url",
                    args.url,
                    "--api-key",
                    args.api_key,
                    "--profile",
                    args.profile,
                    "--provider-mode",
                    "stub",
                    "--provider-name",
                    "matrix-stub",
                    "--provider-model",
                    "deterministic",
                    "--config",
                    str(args.config),
                    "--output-root",
                    str(matrix_dir),
                    "--run-id",
                    run_id,
                    "--requests",
                    str(args.requests_per_cell),
                    "--warmup-requests",
                    "0",
                    "--concurrency",
                    str(concurrency),
                    "--cache-ratio",
                    str(cache_ratio),
                    "--shape",
                    args.shape,
                    "--timeout-seconds",
                    str(args.timeout_seconds),
                ]
                completed = subprocess.run(command, check=False, cwd=ROOT)
                summary_path = matrix_dir / run_id / "summary.json"
                summary = (
                    json.loads(summary_path.read_text(encoding="utf-8"))
                    if summary_path.is_file()
                    else {"error": "summary_not_written"}
                )
                results.append(
                    {
                        "run_id": run_id,
                        "concurrency": concurrency,
                        "cache_ratio": cache_ratio,
                        "repetition": repetition,
                        "exit_code": completed.returncode,
                        "summary": summary,
                    }
                )

    (matrix_dir / "matrix-summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "matrix_id": matrix_id,
                "provider_mode": "stub",
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"matrix_dir": str(matrix_dir), "cells": len(results)}, indent=2))
    return 0 if all(item["exit_code"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
