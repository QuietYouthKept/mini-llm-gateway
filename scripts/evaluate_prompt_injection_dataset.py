"""Aggregate local prompt-injection data against configured Gateway input guardrails.

This runner never emits prompt text. It reads Parquet in bounded batches and
reports label histograms and rule outcomes only. Dataset label semantics and
license must be verified by the operator before interpreting the metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

from app.application.services.guardrail_service import GuardrailService
from app.infrastructure.config.config_models import AppConfig


def summarize_records(records: Iterable[dict[str, Any]], guardrail: GuardrailService) -> dict[str, Any]:
    labels: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    decisions_by_label: dict[str, Counter[str]] = defaultdict(Counter)
    lengths: list[int] = []
    rows = 0
    for record in records:
        text = record.get("text")
        if not isinstance(text, str):
            continue
        rows += 1
        label = str(record.get("label", "missing"))
        labels[label] += 1
        length = len(text)
        lengths.append(length)
        decision = guardrail.check_input(text)
        result = "blocked" if not decision.allowed else "allowed"
        decisions[result] += 1
        decisions_by_label[label][result] += 1

    quantile = statistics.quantiles(lengths, n=100, method="inclusive") if len(lengths) > 1 else []
    return {
        "rows_evaluated": rows,
        "label_histogram": dict(sorted(labels.items())),
        "guardrail_outcomes": dict(sorted(decisions.items())),
        "outcomes_by_label": {
            label: dict(sorted(counts.items()))
            for label, counts in sorted(decisions_by_label.items())
        },
        "text_length_chars": {
            "min": min(lengths) if lengths else None,
            "mean": round(statistics.fmean(lengths), 2) if lengths else None,
            "p50": round(quantile[49], 2) if quantile else (lengths[0] if lengths else None),
            "p95": round(quantile[94], 2) if quantile else (lengths[0] if lengths else None),
            "max": max(lengths) if lengths else None,
        },
        "label_semantics": "unverified; do not interpret as malicious/benign without source metadata",
        "privacy": "prompt text omitted; no per-row identifiers or examples emitted",
    }


def evaluate_file(path: Path, guardrail: GuardrailService, batch_size: int) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    if not {"text", "label"}.issubset(parquet.schema_arrow.names):
        raise ValueError(f"{path.name} must contain text and label columns")

    def records() -> Iterable[dict[str, Any]]:
        for batch in parquet.iter_batches(batch_size=batch_size, columns=["text", "label"]):
            yield from batch.to_pylist()

    result = summarize_records(records(), guardrail)
    with path.open("rb") as source:
        source_hash = hashlib.file_digest(source, "sha256").hexdigest()
    result.update(
        {
            "file_name": path.name,
            "sha256": source_hash,
            "parquet_rows": parquet.metadata.num_rows,
            "row_groups": parquet.metadata.num_row_groups,
            "schema": str(parquet.schema_arrow),
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 1024:
        parser.error("--batch-size must be between 1 and 1024")

    config = AppConfig.from_dict(yaml.safe_load(args.config.read_text(encoding="utf-8")))
    guardrail = GuardrailService(config.guardrails)
    files = sorted(args.dataset_dir.glob("*.parquet"))
    if not files:
        parser.error("dataset directory contains no Parquet files")
    output = {
        "guardrail_policy_version": guardrail.policy_version,
        "dataset_directory": str(args.dataset_dir),
        "source_license": "not supplied / unverified",
        "evaluations": [evaluate_file(path, guardrail, args.batch_size) for path in files],
        "interpretation": (
            "Rule coverage only. This is not model safety, not a general prompt-injection "
            "success rate, and not false-positive/true-positive accuracy until label semantics "
            "and dataset provenance are verified."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "datasets": len(files), "status": "complete"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
