"""Bounded property checks against a locally running Gateway over real TCP.

Run with the separately provisioned Hypothesis environment; only aggregate
counts and database terminal-state totals are written to the result file.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import requests
from hypothesis import given, settings
from hypothesis import strategies as st


def run(base_url: str, api_key: str, database: Path, output: Path) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = False
    headers = {"Authorization": f"Bearer {api_key}"}
    counts: Counter[str] = Counter()
    assertions: Counter[str] = Counter()

    @settings(max_examples=8, derandomize=True, deadline=5000)
    @given(
        prompt=st.text(alphabet=list("abc xyz 你好🙂🚀"), min_size=0, max_size=120),
        max_tokens=st.integers(min_value=1, max_value=16),
        temperature=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def valid_unicode_request(prompt: str, max_tokens: int, temperature: float) -> None:
        response = session.post(
            f"{base_url}/v1/chat",
            headers=headers,
            json={
                "profile": "fast-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=5,
        )
        counts[f"valid_status_{response.status_code}"] += 1
        assert response.status_code == 200, response.text[:200]
        request_id = response.json()["request_id"]
        with sqlite3.connect(database) as connection:
            audits = connection.execute(
                "SELECT count(*) FROM request_logs WHERE request_id=?", (request_id,)
            ).fetchone()[0]
            finalizations = connection.execute(
                "SELECT r.state,f.operation,count(*) FROM token_budget_reservations r "
                "JOIN stream_finalizations f USING(reservation_id) WHERE f.request_id=? "
                "GROUP BY r.state,f.operation",
                (request_id,),
            ).fetchall()
        assert audits == 1
        assert finalizations == [("settled", "settle", 1)]
        assertions["valid_request_persisted_once"] += 1

    @settings(max_examples=4, derandomize=True, deadline=5000)
    @given(field=st.sampled_from(["max_tokens", "temperature"]))
    def boolean_numeric_values_are_rejected(field: str) -> None:
        payload: dict[str, Any] = {
            "profile": "fast-chat",
            "messages": [{"role": "user", "content": "synthetic property probe"}],
            field: True,
        }
        response = session.post(
            f"{base_url}/v1/chat", headers=headers, json=payload, timeout=5
        )
        counts[f"boolean_status_{response.status_code}"] += 1
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assertions["boolean_numeric_rejected"] += 1

    @settings(max_examples=5, derandomize=True, deadline=5000)
    @given(length=st.integers(min_value=4001, max_value=4300))
    def overlong_input_is_blocked(length: int) -> None:
        response = session.post(
            f"{base_url}/v1/chat",
            headers=headers,
            json={
                "profile": "fast-chat",
                "messages": [{"role": "user", "content": "x" * length}],
                "max_tokens": 1,
            },
            timeout=5,
        )
        counts[f"overlong_status_{response.status_code}"] += 1
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "guardrail_blocked"
        assertions["overlong_input_blocked"] += 1

    valid_unicode_request()
    boolean_numeric_values_are_rejected()
    overlong_input_is_blocked()
    session.close()
    result = {
        "status": "PASS",
        "property_groups": 3,
        "valid_unicode_examples": assertions["valid_request_persisted_once"],
        "boolean_numeric_rejection_examples": assertions["boolean_numeric_rejected"],
        "overlong_input_rejection_examples": assertions["overlong_input_blocked"],
        "http_status_counts": dict(sorted(counts.items())),
        "persistent_request_assertions": assertions["valid_request_persisted_once"],
        "privacy": "No prompt values or per-request identifiers written to result.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-key", default="demo-key")
    args = parser.parse_args()
    result = run(args.url.rstrip("/"), args.api_key, args.database, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "http_status_counts"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
