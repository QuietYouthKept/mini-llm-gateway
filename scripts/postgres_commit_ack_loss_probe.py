"""Inject a real TCP loss after PostgreSQL confirms COMMIT, then verify replay."""

from __future__ import annotations

import argparse
import json
import socket
import struct
import threading
import uuid
from contextlib import suppress
from urllib.parse import urlsplit, urlunsplit

from app.application.services.request_log_service import RequestLogService
from app.application.services.token_budget_service import TokenBudgetService
from app.domain.models.provider import ProviderAttempt
from app.domain.ports.repositories import FinalizeStreamCommand
from app.infrastructure.config.config_models import ClientConfig, LoggingConfig, TokenBudgetConfig
from app.infrastructure.persistence.postgresql.connection import connect, migrate
from app.infrastructure.persistence.postgresql.repositories import (
    PostgresClientRepository,
    PostgresRequestLogRepository,
    PostgresStreamingFinalizationRepository,
    PostgresTokenBudgetRepository,
)


class CommitAckLossProxy:
    """Forward PostgreSQL protocol until CommandComplete(COMMIT), then drop ReadyForQuery."""

    _ACCEPT_TIMEOUT_SECONDS = 10
    _SOCKET_TIMEOUT_SECONDS = 15
    _THREAD_JOIN_TIMEOUT_SECONDS = 3

    def __init__(self, database_url: str) -> None:
        parsed = urlsplit(database_url)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            raise ValueError("a PostgreSQL URL with a hostname is required")
        self._upstream = (parsed.hostname, parsed.port or 5432)
        self._url = parsed
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(self._ACCEPT_TIMEOUT_SECONDS)
        self.port = int(self._listener.getsockname()[1])
        self.commit_ack_dropped = threading.Event()
        self.error: str | None = None
        self._relay_thread: threading.Thread | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def relay_thread_stopped(self) -> bool:
        return self._relay_thread is None or not self._relay_thread.is_alive()

    @property
    def proxy_thread_stopped(self) -> bool:
        return not self._thread.is_alive()

    @property
    def database_url(self) -> str:
        return urlunsplit(
            (
                self._url.scheme,
                self._url.netloc.rsplit("@", 1)[0] + "@127.0.0.1:" + str(self.port)
                if "@" in self._url.netloc
                else "127.0.0.1:" + str(self.port),
                self._url.path,
                self._url.query,
                self._url.fragment,
            )
        )

    def _serve(self) -> None:
        client: socket.socket | None = None
        server: socket.socket | None = None
        try:
            client, _ = self._listener.accept()
            server = socket.create_connection(self._upstream, timeout=3)
            client.settimeout(self._SOCKET_TIMEOUT_SECONDS)
            server.settimeout(self._SOCKET_TIMEOUT_SECONDS)
            self._relay_thread = threading.Thread(
                target=self._relay, args=(client, server), daemon=True
            )
            self._relay_thread.start()
            self._relay_backend(server, client)
        except (OSError, TimeoutError) as exc:
            if not self.commit_ack_dropped.is_set():
                self.error = f"{type(exc).__name__}: {exc}"
        finally:
            for stream in (client, server, self._listener):
                if stream is not None:
                    # Closing a socket from another thread does not reliably
                    # wake a blocked recv() on Linux. Shutdown first to unblock
                    # both relay directions, then close the descriptors.
                    with suppress(OSError):
                        stream.shutdown(socket.SHUT_RDWR)
                    with suppress(OSError):
                        stream.close()
            if self._relay_thread is not None:
                self._relay_thread.join(timeout=self._THREAD_JOIN_TIMEOUT_SECONDS)
                if self._relay_thread.is_alive() and self.error is None:
                    self.error = "client relay thread did not exit after socket shutdown"

    @staticmethod
    def _relay(source: socket.socket, destination: socket.socket) -> None:
        try:
            while data := source.recv(65536):
                destination.sendall(data)
        except OSError:
            pass

    def _relay_backend(self, server: socket.socket, client: socket.socket) -> None:
        pending = bytearray()
        message_types = b"ACDEGHIKNQRSTVWZdcfnst"
        while data := server.recv(65536):
            pending.extend(data)
            while pending:
                # PostgreSQL rejects libpq's optional SSLRequest with a single N
                # byte in this local disposable service; preserve it and continue.
                if pending[0] == ord("N"):
                    client.sendall(pending[:1])
                    del pending[:1]
                    continue
                if len(pending) < 5:
                    break
                if pending[0] not in message_types:
                    client.sendall(pending)
                    pending.clear()
                    break
                length = struct.unpack("!I", pending[1:5])[0]
                if length < 4 or length > 64 * 1024 * 1024:
                    client.sendall(pending)
                    pending.clear()
                    break
                frame_length = 1 + length
                if len(pending) < frame_length:
                    break
                frame = bytes(pending[:frame_length])
                del pending[:frame_length]
                is_commit_complete = frame[0] == ord("C") and frame[5:] == b"COMMIT\x00"
                client.sendall(frame)
                if is_commit_complete:
                    # CommandComplete is emitted only after PostgreSQL's COMMIT
                    # command completes. Drop the following ReadyForQuery/ACK.
                    self.commit_ack_dropped.set()
                    return

    def close(self) -> None:
        with suppress(OSError):
            self._listener.shutdown(socket.SHUT_RDWR)
        with suppress(OSError):
            self._listener.close()
        self._thread.join(timeout=self._THREAD_JOIN_TIMEOUT_SECONDS)
        if self._thread.is_alive() and self.error is None:
            self.error = "proxy thread did not exit before deadline"


def run(database_url: str) -> dict[str, object]:
    migrate(database_url)
    suffix = uuid.uuid4().hex
    client = ClientConfig(
        client_id=f"tcp-commit-unknown-{suffix}",
        api_key=f"synthetic-{suffix}",
        token_budget=TokenBudgetConfig(period="daily", max_tokens=100),
    )
    PostgresClientRepository(database_url).sync([client])
    request_id = f"tcp-commit-unknown-request-{suffix}"
    reservation_id = f"{request_id}:reservation"
    budget = TokenBudgetService(PostgresTokenBudgetRepository(database_url))
    budget.reserve(reservation_id, client, 25, 0.0)
    request_log = RequestLogService(PostgresRequestLogRepository(database_url), LoggingConfig())
    request_row, attempts = request_log.build_stream_record(
        request_id=request_id,
        client_id=client.client_id,
        model_profile="reliability-probe",
        endpoint="/probe/commit-ack-loss",
        selected_provider="synthetic-provider",
        status="completed",
        status_code=200,
        usage={
            "billed_input": 7,
            "billed_output": 5,
            "actual_input": 7,
            "actual_output": 5,
            "source": "provider",
        },
        estimated_input=7,
        estimated_output=5,
        estimated_cost_usd=0.0,
        budget_before=100,
        duration_ms=1,
        attempts=[
            ProviderAttempt(
                provider_id="synthetic-provider",
                attempt_order=0,
                status="success",
                provider_request_id=f"upstream-{suffix}",
            )
        ],
        decision_trace=[{"step": "provider_selected", "provider": "synthetic-provider"}],
        replay_payload=None,
        response_content="synthetic result",
    )
    command = FinalizeStreamCommand(
        reservation_id=reservation_id,
        request_id=request_id,
        operation="settle",
        tokens=12,
        cost_usd=0.0,
        payload_fingerprint=f"fingerprint-{suffix}",
        request_row=request_row,
        attempts=attempts,
    )

    proxy = CommitAckLossProxy(database_url)
    observed_error: str | None = None
    try:
        try:
            PostgresStreamingFinalizationRepository(proxy.database_url).finalize_stream(command)
        except Exception as exc:  # expected: client did not receive ReadyForQuery
            observed_error = f"{type(exc).__module__}.{type(exc).__name__}"
    finally:
        proxy.close()

    finalizer = PostgresStreamingFinalizationRepository(database_url)
    receipt = finalizer.get_finalization(reservation_id)
    replay = finalizer.finalize_stream(command)
    with connect(database_url) as conn:
        rows = conn.execute(
            """SELECT r.state, f.operation, f.tokens, u.tokens_used,
            (SELECT count(*) FROM request_logs WHERE request_id=%s) AS audit_count,
            (SELECT count(*) FROM provider_attempts WHERE request_id=%s) AS attempt_count
            FROM token_budget_reservations r
            JOIN stream_finalizations f USING (reservation_id)
            JOIN token_budget_usage u ON u.client_id=r.client_id AND u.period=r.period
            WHERE r.reservation_id=%s""",
            (request_id, request_id, reservation_id),
        ).fetchone()

    result: dict[str, object] = {
        "commit_command_completed_on_wire": proxy.commit_ack_dropped.is_set(),
        "ready_for_query_ack_dropped": proxy.commit_ack_dropped.is_set(),
        "client_observed_commit_error": observed_error,
        "proxy_error": proxy.error,
        "relay_thread_stopped": proxy.relay_thread_stopped,
        "proxy_thread_stopped": proxy.proxy_thread_stopped,
        "receipt_recovered_directly": receipt is not None,
        "receipt_state": receipt.state if receipt else None,
        "idempotent_replay": replay.already_applied,
        "reservation_state": rows["state"] if rows else None,
        "operation": rows["operation"] if rows else None,
        "receipt_tokens": rows["tokens"] if rows else None,
        "usage_tokens": rows["tokens_used"] if rows else None,
        "audit_count": rows["audit_count"] if rows else None,
        "attempt_count": rows["attempt_count"] if rows else None,
    }
    result["oracle_pass"] = bool(
        result["commit_command_completed_on_wire"]
        and result["client_observed_commit_error"]
        and result["receipt_recovered_directly"]
        and result["receipt_state"] == "settled"
        and result["idempotent_replay"] is True
        and result["reservation_state"] == "settled"
        and result["operation"] == "settle"
        and result["receipt_tokens"] == 12
        and result["usage_tokens"] == 12
        and result["audit_count"] == 1
        and result["attempt_count"] == 1
        and result["relay_thread_stopped"] is True
        and result["proxy_thread_stopped"] is True
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    result = run(args.database_url)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["oracle_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
