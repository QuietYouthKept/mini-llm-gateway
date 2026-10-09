"""Exercise the disposable Docker Compose staging release and failure paths."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PROJECT = os.getenv("WAVE4_COMPOSE_PROJECT", "mini-llm-gateway-wave3-staging")
BASE_URL = os.getenv("WAVE4_BASE_URL", "http://127.0.0.1:8000")
DATABASE_URL = "postgresql://gateway@postgres:5432/gateway"


def compose(*args: str, image: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    if image is not None:
        environment["GATEWAY_IMAGE"] = image
    return subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, *args],
        cwd=ROOT,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
        timeout=180,
    )


def wait_http(path: str, expected: set[int], timeout: float = 60) -> httpx.Response:
    deadline = time.monotonic() + timeout
    last: httpx.Response | None = None
    while time.monotonic() < deadline:
        try:
            last = httpx.get(BASE_URL + path, timeout=2, trust_env=False)
            if last.status_code in expected:
                return last
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {path}; last status={last.status_code if last else None}")


def api_version() -> str:
    response = wait_http("/openapi.json", {200})
    return str(response.json()["info"]["version"])


def query_postgres(sql: str, parameters: tuple[Any, ...] = ()) -> list[list[Any]]:
    python = (
        "import json, psycopg; "
        f"connection=psycopg.connect({DATABASE_URL!r}); "
        f"cursor=connection.execute({sql!r}, {parameters!r}); "
        "rows=cursor.fetchall() if cursor.description else []; "
        "connection.commit(); print(json.dumps(rows, default=str)); connection.close()"
    )
    result = compose("exec", "-T", "gateway", "python", "-c", python)
    return json.loads(result.stdout)


def smoke_stream() -> dict[str, Any]:
    payload = {
        "profile": "fast-chat",
        "stream": True,
        "messages": [{"role": "user", "content": "wave3 disposable container smoke"}],
        "max_tokens": 16,
    }
    with httpx.stream(
        "POST",
        BASE_URL + "/v1/chat",
        headers={"Authorization": "Bearer demo-key"},
        json=payload,
        timeout=20,
        trust_env=False,
    ) as response:
        body = "".join(response.iter_text())
        request_id = response.headers.get("x-request-id", "")
        status_code = response.status_code
    events = {
        line.removeprefix("event: ")
        for line in body.splitlines()
        if line.startswith("event: ")
    }
    audit_response = httpx.get(
        BASE_URL + f"/v1/requests/{request_id}",
        headers={"Authorization": "Bearer demo-key"},
        timeout=5,
        trust_env=False,
    )
    reservation = query_postgres(
        "SELECT state FROM token_budget_reservations WHERE reservation_id LIKE %s",
        (f"{request_id}:%",),
    )
    receipt = query_postgres(
        "SELECT operation FROM stream_finalizations WHERE request_id=%s", (request_id,)
    )
    audit_count = query_postgres(
        "SELECT count(*) FROM request_logs WHERE request_id=%s", (request_id,)
    )[0][0]
    return {
        "http_status": status_code,
        "request_id_present": bool(request_id),
        "events": sorted(events),
        "audit_http_status": audit_response.status_code,
        "reservation_state": reservation[0][0] if reservation else None,
        "finalization_operation": receipt[0][0] if receipt else None,
        "request_audit_rows": audit_count,
        "oracle_pass": (
            status_code == 200
            and bool(request_id)
            and {"message", "usage", "done"}.issubset(events)
            and audit_response.status_code == 200
            and bool(reservation)
            and reservation[0][0] == "settled"
            and bool(receipt)
            and receipt[0][0] == "settle"
            and audit_count == 1
        ),
    }


def tcp_client_disconnect() -> dict[str, Any]:
    request_id = f"wave3-client-disconnect-{uuid.uuid4().hex}"
    payload = {
        "profile": "fast-chat",
        "stream": True,
        "messages": [{"role": "user", "content": "disconnect " + "x" * 1400}],
        "max_tokens": 512,
    }
    observed_message = False
    with httpx.stream(
        "POST",
        BASE_URL + "/v1/chat",
        headers={"Authorization": "Bearer demo-key", "x-request-id": request_id},
        json=payload,
        timeout=20,
        trust_env=False,
    ) as response:
        for line in response.iter_lines():
            if line == "event: message":
                observed_message = True
                break
    audit = query_postgres(
        "SELECT status,error_code FROM request_logs WHERE request_id=%s", (request_id,)
    )
    state = query_postgres(
        "SELECT r.state,f.operation FROM token_budget_reservations r "
        "LEFT JOIN stream_finalizations f USING(reservation_id) "
        "WHERE r.reservation_id LIKE %s",
        (f"{request_id}:%",),
    )
    attempts = query_postgres(
        "SELECT status FROM provider_attempts WHERE request_id=%s ORDER BY attempt_order",
        (request_id,),
    )
    return {
        "message_received_before_disconnect": observed_message,
        "audit_status": audit[0][0] if audit else None,
        "audit_error_code": audit[0][1] if audit else None,
        "reservation_state": state[0][0] if state else None,
        "finalization_operation": state[0][1] if state else None,
        "provider_attempts": [row[0] for row in attempts],
        "audit_rows": len(audit),
        "oracle_pass": (
            observed_message
            and bool(audit)
            and audit[0][0] == "cancelled"
            and bool(state)
            and state[0][0] in {"settled", "released"}
            and len(audit) == 1
            and bool(attempts)
            and attempts[-1][0] == "cancelled"
        ),
    }


def tcp_settlement_failure() -> dict[str, Any]:
    request_id = f"wave3-settlement-failure-{uuid.uuid4().hex}"
    suffix = uuid.uuid4().hex[:12]
    function_name = f"wave3_fail_audit_{suffix}"
    trigger_name = f"wave3_fail_audit_trigger_{suffix}"
    query_postgres(
        f"CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN IF NEW.request_id = '{request_id}' THEN "
        "RAISE EXCEPTION 'injected Wave 3 settlement audit failure'; END IF; "
        "RETURN NEW; END $$"
    )
    query_postgres(
        f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON request_logs "
        f"FOR EACH ROW EXECUTE FUNCTION {function_name}()"
    )
    payload = {
        "profile": "fast-chat",
        "stream": True,
        "messages": [{"role": "user", "content": "injected settlement audit failure"}],
        "max_tokens": 16,
    }
    with httpx.stream(
        "POST",
        BASE_URL + "/v1/chat",
        headers={"Authorization": "Bearer demo-key", "x-request-id": request_id},
        json=payload,
        timeout=20,
        trust_env=False,
    ) as response:
        status_code = response.status_code
        body = "".join(response.iter_text())
    query_postgres(f"DROP TRIGGER {trigger_name} ON request_logs")
    query_postgres(f"DROP FUNCTION {function_name}()")
    state = query_postgres(
        "SELECT state FROM token_budget_reservations WHERE reservation_id LIKE %s",
        (f"{request_id}:%",),
    )
    receipt_rows = query_postgres(
        "SELECT count(*) FROM stream_finalizations WHERE request_id=%s", (request_id,)
    )[0][0]
    audit_rows = query_postgres(
        "SELECT count(*) FROM request_logs WHERE request_id=%s", (request_id,)
    )[0][0]
    error_event = next((line for line in body.splitlines() if line.startswith("data: ") and '"code"' in line), "")
    return {
        "http_status": status_code,
        "error_event_present": "event: error" in body,
        "error_event": error_event,
        "reservation_state": state[0][0] if state else None,
        "receipt_rows": receipt_rows,
        "audit_rows": audit_rows,
        "oracle_pass": (
            status_code == 200
            and "event: error" in body
            and '"code":"stream_finalization_unknown"' in body
            and bool(state)
            and state[0][0] == "reserved"
            and receipt_rows == 0
            and audit_rows == 0
        ),
    }
def wait_service_healthy(service: str, timeout: float = 50) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = compose("ps", "--format", "{{.Health}}", service, check=False)
        if "healthy" in result.stdout:
            return
        time.sleep(1)
    raise TimeoutError(f"Compose service {service} did not become healthy")


def readiness_status() -> int:
    try:
        return httpx.get(BASE_URL + "/ready", timeout=3, trust_env=False).status_code
    except httpx.HTTPError:
        return 0


def run(
    wave2_image: str,
    wave3_image: str,
    postgres_concurrencies: list[int] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"staging_started": False}
    try:
        compose("up", "-d", "--no-build", image=wave3_image)
        evidence["staging_started"] = True
        wait_http("/ready", {200})
        evidence["versions"] = {"wave3_initial": api_version()}

        # Re-running the immutable migration set must be a no-op.
        first = compose("exec", "-T", "gateway", "python", "scripts/migrate_postgres.py")
        second = compose("exec", "-T", "gateway", "python", "scripts/migrate_postgres.py")
        evidence["migration_repeat"] = {
            "first_exit": first.returncode,
            "second_exit": second.returncode,
            "oracle_pass": first.returncode == second.returncode == 0,
        }
        pg_probe = compose(
            "exec", "-T", "gateway", "python", "-m", "scripts.postgres_integration_probe",
            "--database-url", DATABASE_URL,
        )
        evidence["postgres_repository_matrix"] = json.loads(pg_probe.stdout)
        evidence["postgres_repository_matrix"]["oracle_pass"] = pg_probe.returncode == 0

        inspect = subprocess.check_output(
            ["docker", "inspect", f"{COMPOSE_PROJECT}-gateway-1"],
            text=True,
        )
        container = json.loads(inspect)[0]
        evidence["container_security"] = {
            "user": container["Config"]["User"],
            "read_only_rootfs": container["HostConfig"]["ReadonlyRootfs"],
            "config_mount_read_only": any(
                mount["Destination"] == "/app/config" and not mount["RW"]
                for mount in container["Mounts"]
            ),
            "healthcheck_present": bool(container["Config"].get("Healthcheck")),
            "tmpfs_present": any(mount.startswith("/tmp") for mount in container["HostConfig"].get("Tmpfs", {})),
        }
        root_write = compose(
            "exec", "-T", "gateway", "python", "-c",
            "from pathlib import Path; Path('/app/wave3-write-test').write_text('no')",
            check=False,
        )
        tmp_write = compose(
            "exec", "-T", "gateway", "python", "-c",
            "from pathlib import Path; Path('/tmp/wave3-write-test').write_text('ok')",
        )
        evidence["container_security"].update(
            {
                "application_path_write_rejected": root_write.returncode != 0,
                "tmpfs_write_succeeded": tmp_write.returncode == 0,
                "oracle_pass": (
                    container["Config"]["User"] == "10001:10001"
                    and container["HostConfig"]["ReadonlyRootfs"] is True
                    and evidence["container_security"]["config_mount_read_only"]
                    and evidence["container_security"]["healthcheck_present"]
                    and evidence["container_security"]["tmpfs_present"]
                    and root_write.returncode != 0
                    and tmp_write.returncode == 0
                ),
            }
        )
        evidence["http_sse_smoke"] = smoke_stream()
        evidence["tcp_client_disconnect"] = tcp_client_disconnect()
        evidence["tcp_settlement_failure"] = tcp_settlement_failure()

        compose("stop", "redis")
        time.sleep(2)
        redis_readiness = readiness_status()
        redis_request_id = f"wave3-redis-outage-{uuid.uuid4().hex}"
        redis_failure = httpx.post(
            BASE_URL + "/v1/chat",
            headers={"Authorization": "Bearer demo-key", "x-request-id": redis_request_id},
            json={"profile": "fast-chat", "messages": [{"role": "user", "content": "redis outage"}]},
            timeout=15,
            trust_env=False,
        )
        evidence["redis_outage"] = {
            "readiness_status": redis_readiness,
            "request_status": redis_failure.status_code,
            "error_code": redis_failure.json().get("error", {}).get("code"),
        }
        compose("start", "redis")
        wait_service_healthy("redis")
        wait_http("/ready", {200})
        redis_recovered = httpx.post(
            BASE_URL + "/v1/chat",
            headers={"Authorization": "Bearer demo-key"},
            json={"profile": "fast-chat", "messages": [{"role": "user", "content": "redis recovered"}]},
            timeout=10,
            trust_env=False,
        )
        evidence["redis_outage"]["recovery_status"] = redis_recovered.status_code
        redis_audit = query_postgres(
            "SELECT status,error_code FROM request_logs WHERE request_id=%s",
            (redis_request_id,),
        )
        redis_reservations = query_postgres(
            "SELECT count(*) FROM token_budget_reservations WHERE reservation_id LIKE %s",
            (f"{redis_request_id}:%",),
        )[0][0]
        evidence["redis_outage"]["request_audit"] = redis_audit[0] if redis_audit else None
        evidence["redis_outage"]["reservation_rows"] = redis_reservations
        evidence["redis_outage"]["oracle_pass"] = (
            redis_readiness == 503
            and redis_failure.status_code == 503
            and evidence["redis_outage"]["error_code"] == "rate_limit_backend_unavailable"
            and redis_recovered.status_code == 200
            and bool(redis_audit)
            and redis_audit[0] == ["error", "rate_limit_backend_unavailable"]
            and redis_reservations == 0
        )

        outage_matrix: list[dict[str, Any]] = []
        for concurrency in postgres_concurrencies or [20]:
            compose("stop", "postgres")
            time.sleep(2)
            outage_started = time.monotonic()
            outage_ids = [
                f"wave41-postgres-outage-{concurrency}-{uuid.uuid4().hex}"
                for _ in range(concurrency)
            ]

            def post_during_outage(request_id: str) -> dict[str, Any]:
                request_started = time.monotonic()
                try:
                    response = httpx.post(
                        BASE_URL + "/v1/chat",
                        headers={
                            "Authorization": "Bearer demo-key",
                            "x-request-id": request_id,
                        },
                        json={
                            "profile": "fast-chat",
                            "messages": [
                                {"role": "user", "content": "synthetic postgres outage"}
                            ],
                        },
                        timeout=8,
                        trust_env=False,
                    )
                    return {
                        "status": response.status_code,
                        "error_code": response.json().get("error", {}).get("code"),
                        "duration_seconds": time.monotonic() - request_started,
                    }
                except httpx.HTTPError as exc:
                    return {
                        "status": 0,
                        "error_code": None,
                        "transport_error": type(exc).__name__,
                        "duration_seconds": time.monotonic() - request_started,
                    }

            with ThreadPoolExecutor(max_workers=concurrency) as clients:
                requests_future = [
                    clients.submit(post_during_outage, request_id) for request_id in outage_ids
                ]
                time.sleep(0.05)
                live_started = time.monotonic()
                live_status = httpx.get(
                    BASE_URL + "/live", timeout=1, trust_env=False
                ).status_code
                live_duration = time.monotonic() - live_started
                ready_started = time.monotonic()
                pg_readiness = readiness_status()
                ready_duration = time.monotonic() - ready_started
                pg_results = [future.result() for future in requests_future]
            outage_duration = time.monotonic() - outage_started
            compose("start", "postgres")
            wait_service_healthy("postgres")
            wait_http("/ready", {200})
            audit_counts = [
                query_postgres(
                    "SELECT count(*) FROM request_logs WHERE request_id=%s", (item,)
                )[0][0]
                for item in outage_ids
            ]
            reservation_counts = [
                query_postgres(
                    "SELECT count(*) FROM token_budget_reservations WHERE reservation_id LIKE %s",
                    (f"{item}:%",),
                )[0][0]
                for item in outage_ids
            ]
            outage_matrix.append(
                {
                    "concurrency": concurrency,
                    "readiness_status": pg_readiness,
                    "readiness_duration_seconds": ready_duration,
                    "live_status": live_status,
                    "live_duration_seconds": live_duration,
                    "request_statuses": [item["status"] for item in pg_results],
                    "request_error_codes": [item["error_code"] for item in pg_results],
                    "request_durations_seconds": [
                        item["duration_seconds"] for item in pg_results
                    ],
                    "max_request_duration_seconds": max(
                        (item["duration_seconds"] for item in pg_results), default=0
                    ),
                    "outage_experiment_duration_seconds": outage_duration,
                    "recovery_readiness_status": readiness_status(),
                    "request_audit_row_counts": audit_counts,
                    "reservation_row_counts": reservation_counts,
                    "oracle_pass": (
                        pg_readiness == 503
                        and ready_duration < 2
                        and live_status == 200
                        and live_duration < 1
                        and len(pg_results) == concurrency
                        and all(item["status"] == 503 for item in pg_results)
                        and max(
                            (item["duration_seconds"] for item in pg_results), default=99
                        ) < 5
                        and all(count == 0 for count in reservation_counts)
                        and all(count == 0 for count in audit_counts)
                    ),
                }
            )
        evidence["postgres_outage_matrix"] = outage_matrix
        evidence["postgres_outage"] = {
            "concurrencies": [item["concurrency"] for item in outage_matrix],
            "oracle_pass": bool(outage_matrix)
            and all(item["oracle_pass"] for item in outage_matrix),
        }

        first_message = threading.Event()
        stream_result: dict[str, Any] = {}

        def active_stream() -> None:
            payload = {
                "profile": "fast-chat",
                "stream": True,
                "messages": [{"role": "user", "content": "shutdown stream " + "x" * 1400}],
                "max_tokens": 512,
            }
            try:
                with httpx.stream(
                    "POST",
                    BASE_URL + "/v1/chat",
                    headers={"Authorization": "Bearer demo-key"},
                    json=payload,
                    timeout=30,
                    trust_env=False,
                ) as response:
                    stream_result["status"] = response.status_code
                    stream_result["request_id"] = response.headers.get("x-request-id", "")
                    for line in response.iter_lines():
                        if line == "event: message":
                            first_message.set()
                        if line == "event: done":
                            stream_result["completed"] = True
            except httpx.HTTPError as exc:
                stream_result["disconnect"] = type(exc).__name__

        stream_thread = threading.Thread(target=active_stream, daemon=True)
        stream_thread.start()
        if not first_message.wait(timeout=15):
            raise TimeoutError("Could not start the active SSE request before SIGTERM")
        compose("stop", "--timeout", "15", "gateway")
        stream_thread.join(timeout=10)
        stopped = subprocess.check_output(
            ["docker", "inspect", f"{COMPOSE_PROJECT}-gateway-1"], text=True
        )
        stopped_container = json.loads(stopped)[0]
        compose("start", "gateway", image=wave3_image)
        wait_http("/ready", {200})
        stream_state = query_postgres(
            "SELECT state FROM token_budget_reservations WHERE reservation_id LIKE %s",
            (f"{stream_result.get('request_id', '')}:%",),
        )
        stream_audit_rows = query_postgres(
            "SELECT count(*) FROM request_logs WHERE request_id=%s",
            (stream_result.get("request_id", ""),),
        )[0][0]
        evidence["sigterm"] = {
            "exit_code": stopped_container["State"].get("ExitCode"),
            "oom_killed": stopped_container["State"].get("OOMKilled"),
            "active_stream_started": first_message.is_set(),
            "stream_reservation_state": stream_state[0][0] if stream_state else None,
            "stream_audit_rows": stream_audit_rows,
            "stream_thread_stopped": not stream_thread.is_alive(),
        }
        evidence["sigterm"]["recovery_status"] = readiness_status()
        evidence["sigterm"]["oracle_pass"] = (
            evidence["sigterm"]["exit_code"] == 0
            and evidence["sigterm"]["oom_killed"] is False
            and evidence["sigterm"]["recovery_status"] == 200
            and evidence["sigterm"]["active_stream_started"]
            and evidence["sigterm"]["stream_reservation_state"] in {"settled", "released"}
            and evidence["sigterm"]["stream_audit_rows"] == 1
            and evidence["sigterm"]["stream_thread_stopped"]
        )

        evidence["upgrade_and_rollback"] = {}
        for label, image, expected in (
            ("wave2", wave2_image, "1.0.0rc1"),
            ("wave3", wave3_image, "1.0.0rc2"),
            ("rollback_wave2", wave2_image, "1.0.0rc1"),
        ):
            compose("up", "-d", "--no-deps", "gateway", image=image)
            if expected == "1.0.0rc1":
                wait_http("/live", {200})
            else:
                wait_http("/ready", {200})
            actual = api_version()
            live_status = httpx.get(BASE_URL + "/live", timeout=3, trust_env=False).status_code
            ready_status = readiness_status()
            rollback_request_status = None
            rollback_audit = None
            if expected == "1.0.0rc1":
                rollback_request_id = f"wave3-{label}-smoke-{uuid.uuid4().hex}"
                rollback_response = httpx.post(
                    BASE_URL + "/v1/chat",
                    headers={
                        "Authorization": "Bearer demo-key",
                        "x-request-id": rollback_request_id,
                    },
                    json={
                        "profile": "fast-chat",
                        "messages": [{"role": "user", "content": "rollback smoke"}],
                    },
                    timeout=15,
                    trust_env=False,
                )
                rollback_request_status = rollback_response.status_code
                audit_rows = query_postgres(
                    "SELECT status,error_code FROM request_logs WHERE request_id=%s",
                    (rollback_request_id,),
                )
                rollback_audit = audit_rows[0] if audit_rows else None
            evidence["upgrade_and_rollback"][label] = {
                "image": image,
                "version": actual,
                "expected": expected,
                "live_status": live_status,
                "readiness_status": ready_status,
                "rollback_request_status": rollback_request_status,
                "rollback_request_audit": rollback_audit,
                "functional_smoke_pass": (
                    expected != "1.0.0rc1"
                    or (rollback_request_status == 200 and rollback_audit == ["success", None])
                ),
                "oracle_pass": (
                    actual == expected
                    and live_status == 200
                    and ready_status == 200
                    and (
                        expected != "1.0.0rc1"
                        or (rollback_request_status == 200 and rollback_audit == ["success", None])
                    )
                ),
            }
        evidence["upgrade_and_rollback"]["oracle_pass"] = all(
            step["oracle_pass"]
            for step in evidence["upgrade_and_rollback"].values()
            if isinstance(step, dict)
        )
        evidence["oracle_pass"] = all(
            value.get("oracle_pass", False)
            for value in evidence.values()
            if isinstance(value, dict) and "oracle_pass" in value
        )
        return evidence
    except Exception as exc:
        evidence["error_class"] = type(exc).__name__
        evidence["error_message"] = str(exc)[:500]
        evidence["oracle_pass"] = False
        return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wave2-image", required=True)
    parser.add_argument("--wave3-image", required=True)
    parser.add_argument(
        "--postgres-concurrencies", nargs="+", type=int, default=[20]
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        args.wave2_image,
        args.wave3_image,
        postgres_concurrencies=args.postgres_concurrencies,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    compose("down", check=False)
    return 0 if result.get("oracle_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
