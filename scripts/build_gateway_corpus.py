"""Build small deterministic Gateway workloads from read-only public Parquet data.

This script never writes below ``public/``.  It emits normalized JSONL plus a
metadata sidecar containing provenance and a content checksum.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import pyarrow.parquet as pq
except ImportError as exc:  # pragma: no cover - environment gate
    raise SystemExit("pyarrow is required: run this script with a Python that has pyarrow") from exc

DEFAULT_ROOT = Path(r"E:\project-test-assets\01-gateway")


def _files(root: Path, source: str) -> list[Path]:
    if source == "ultrachat":
        files = sorted((root / "public" / source).glob("test_sft-*.parquet"))
    else:
        files = sorted((root / "public" / source).glob("train-*.parquet"))
    if not files:
        raise SystemExit(f"No {source} parquet files found below {root / 'public'}")
    return files


def _normalize(source: str, row: dict[str, Any]) -> dict[str, Any] | None:
    raw_messages = row.get("messages" if source == "ultrachat" else "conversation") or []
    messages = []
    for message in raw_messages:
        if source == "wildchat" and (message.get("redacted") or message.get("toxic")):
            return None
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role not in {"system", "user", "assistant"} or not content:
            continue
        messages.append({"role": role, "content": content})
    if not messages or not any(message["role"] == "user" for message in messages):
        return None
    if source == "wildchat" and (row.get("redacted") or row.get("toxic")):
        return None
    identifier = row.get("prompt_id") or row.get("conversation_id")
    return {
        "dataset": source,
        "record_id": str(identifier or ""),
        "messages": messages,
        "message_count": len(messages),
        "character_count": sum(len(message["content"]) for message in messages),
    }


def _rows(files: list[Path], source: str) -> Iterable[dict[str, Any]]:
    columns = ["prompt_id", "messages"] if source == "ultrachat" else [
        "conversation_id",
        "conversation",
        "toxic",
        "redacted",
    ]
    for path in files:
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=2048, columns=columns):
            for raw in batch.to_pylist():
                normalized = _normalize(source, raw)
                if normalized is not None:
                    yield normalized


def _reservoir(rows: Iterable[dict[str, Any]], count: int, seed: int) -> tuple[list[dict], int]:
    rng = random.Random(seed)
    sample: list[dict] = []
    eligible = 0
    for eligible, row in enumerate(rows, start=1):
        if len(sample) < count:
            sample.append(row)
        else:
            replace_at = rng.randrange(eligible)
            if replace_at < count:
                sample[replace_at] = row
    if eligible < count:
        raise SystemExit(f"Requested {count} samples but only {eligible} eligible rows exist")
    sample.sort(key=lambda item: (item["record_id"], item["character_count"]))
    return sample, eligible


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(root: Path, source: str, samples: int, seed: int, output: Path | None) -> Path:
    files = _files(root, source)
    selected, eligible = _reservoir(_rows(files, source), samples, seed)
    fixture_dir = root / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    target = output or fixture_dir / f"{source}_gateway_{samples}_seed{seed}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for item in selected:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    metadata = {
        "evidence_labels": ["PUBLIC DATA", "GENERATED"],
        "source": source,
        "original_files": [str(path) for path in files],
        "original_rows": sum(pq.ParquetFile(path).metadata.num_rows for path in files),
        "eligible_rows": eligible,
        "sample_count": len(selected),
        "seed": seed,
        "schema": {
            "dataset": "string",
            "record_id": "string",
            "messages": "list[{role:string,content:string}]",
            "message_count": "integer",
            "character_count": "integer",
        },
        "checksum_sha256": _sha256(target),
        "created_at": datetime.now(UTC).isoformat(),
        "raw_data_mutated": False,
    }
    sidecar = target.with_suffix(".metadata.json")
    sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("wildchat", "ultrachat"), required=True)
    parser.add_argument("--samples", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples <= 0:
        parser.error("--samples must be positive")
    target = build(args.root, args.source, args.samples, args.seed, args.output)
    print(target)
    print(target.with_suffix(".metadata.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
