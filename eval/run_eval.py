"""Run the config-driven eval harness.

Loads eval/eval_cases.yaml, executes each case against an in-process gateway
(fresh temp DB), and reports pass/fail. Exits non-zero on any failure.

    make eval            # or: python eval/run_eval.py
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import warnings
from typing import Any

warnings.filterwarnings("ignore", message=".*testclient.*deprecated.*")

import yaml
from fastapi.testclient import TestClient

from app.core.startup import bootstrap
from app.main import create_app

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.yaml")
CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_cases.yaml")


def _build_body(raw: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = dict(raw)
    messages = []
    for m in body.get("messages", []):
        msg = {"role": m["role"], "content": m.get("content", "")}
        if m.get("repeat"):
            msg["content"] = msg["content"] * int(m["repeat"])
        messages.append(msg)
    body["messages"] = messages
    return body


def _check(expect: dict[str, Any], resp) -> tuple[bool, str]:
    failures: list[str] = []
    body = resp.json() if resp.content else {}

    if "status" in expect and resp.status_code != expect["status"]:
        failures.append(f"status {resp.status_code} != {expect['status']}")
    if "provider" in expect and body.get("provider") != expect["provider"]:
        failures.append(f"provider {body.get('provider')} != {expect['provider']}")
    if "fallback_used" in expect and body.get("fallback_used") != expect["fallback_used"]:
        failures.append(f"fallback_used {body.get('fallback_used')} != {expect['fallback_used']}")
    if "error_code" in expect and body.get("error", {}).get("code") != expect["error_code"]:
        failures.append(f"error_code {body.get('error', {}).get('code')} != {expect['error_code']}")
    if "cache_hit" in expect and body.get("cache_hit") != expect["cache_hit"]:
        failures.append(f"cache_hit {body.get('cache_hit')} != {expect['cache_hit']}")

    if failures:
        return False, "; ".join(failures)
    return True, "ok"


def main(cases_path: str) -> int:
    with open(cases_path, encoding="utf-8") as f:
        cases = yaml.safe_load(f)["cases"]

    with tempfile.TemporaryDirectory() as tmp:
        container = bootstrap(config_path=CONFIG_PATH, database_path=os.path.join(tmp, "eval.db"))
        app = create_app(container=container)

        passed = 0
        with TestClient(app) as client:
            for case in cases:
                headers = {}
                if case.get("api_key"):
                    headers["Authorization"] = f"Bearer {case['api_key']}"
                resp = client.post(case["endpoint"], json=_build_body(case["body"]), headers=headers)
                ok, detail = _check(case["expect"], resp)
                if ok:
                    passed += 1
                print(f"[{'PASS' if ok else 'FAIL'}] {case['id']}  ({detail})")

    print(f"\n{passed}/{len(cases)} cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the config-driven eval harness.")
    parser.add_argument("--cases", default=CASES_PATH, help="Path to a cases YAML file.")
    args = parser.parse_args()
    sys.exit(main(args.cases))
