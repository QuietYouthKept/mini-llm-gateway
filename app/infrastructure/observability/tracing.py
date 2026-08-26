"""Small bounded tracing seam used when OpenTelemetry is not installed."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpanRecord:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    duration_ms: float = 0.0


class TraceRecorder:
    """Bounded in-process recorder and future OpenTelemetry adapter seam."""

    def __init__(self, *, enabled: bool = True, max_spans: int = 2048) -> None:
        self.enabled = enabled
        self._spans: deque[SpanRecord] = deque(maxlen=max(1, max_spans))

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[SpanRecord]:
        record = SpanRecord(name=name, attributes=dict(attributes or {}))
        if not self.enabled:
            yield record
            return
        start = time.monotonic()
        try:
            yield record
        except BaseException:
            record.status = "error"
            raise
        finally:
            record.duration_ms = (time.monotonic() - start) * 1000.0
            self._spans.append(record)

    def snapshot(self) -> list[SpanRecord]:
        return list(self._spans)


class OpenTelemetryTraceRecorder(TraceRecorder):
    """OTLP-exporting recorder that retains the bounded local debug snapshot."""

    def __init__(self, endpoint: str, *, max_spans: int = 2048) -> None:
        super().__init__(enabled=True, max_spans=max_spans)
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:  # pragma: no cover - environment gate
            raise RuntimeError("OTLP export requires OpenTelemetry SDK dependencies") from exc
        self._provider = TracerProvider(
            resource=Resource.create({"service.name": "mini-llm-gateway"})
        )
        self._provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        self._otel_tracer = self._provider.get_tracer("mini-llm-gateway")

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[SpanRecord]:
        from opentelemetry.trace import Status, StatusCode

        record = SpanRecord(name=name, attributes=dict(attributes or {}))
        start = time.monotonic()
        with self._otel_tracer.start_as_current_span(name) as otel_span:
            try:
                yield record
            except BaseException:
                record.status = "error"
                otel_span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                record.duration_ms = (time.monotonic() - start) * 1000.0
                for key, value in record.attributes.items():
                    if isinstance(value, (str, bool, int, float)):
                        otel_span.set_attribute(key, value)
                self._spans.append(record)

    def close(self) -> None:
        self._provider.force_flush(timeout_millis=5000)
        self._provider.shutdown()
