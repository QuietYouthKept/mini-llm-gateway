"""Minimal Prometheus metrics registry (text exposition format).

Hand-rolled to avoid an extra dependency; supports Counter, Gauge, and a
fixed-bucket Histogram, which is all the gateway needs.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterable

_DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_NL = chr(10)


def _label_key(labels: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(labels))


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + inner + "}"


class _Counter:
    def __init__(self) -> None:
        self._values: dict[tuple, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, value: float = 1.0, labels: Iterable[tuple[str, str]] = ()) -> None:
        with self._lock:
            self._values[_label_key(labels)] += value

    def samples(self) -> list[tuple[tuple, float]]:
        with self._lock:
            return list(self._values.items())


class _Gauge(_Counter):
    def set(self, value: float, labels: Iterable[tuple[str, str]] = ()) -> None:
        with self._lock:
            self._values[_label_key(labels)] = value


class _Histogram:
    def __init__(self, buckets: tuple[float, ...]) -> None:
        self._buckets = tuple(buckets)
        self._counts: dict[tuple, dict[float, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._sums: dict[tuple, float] = defaultdict(float)
        self._count_total: dict[tuple, int] = defaultdict(int)
        self._lock = threading.Lock()

    def observe(self, value: float, labels: Iterable[tuple[str, str]] = ()) -> None:
        key = _label_key(labels)
        with self._lock:
            self._sums[key] += value
            self._count_total[key] += 1
            for b in self._buckets:
                if value <= b:
                    self._counts[key][b] += 1

    def samples(self) -> list[tuple[str, tuple, float]]:
        with self._lock:
            out: list[tuple[str, tuple, float]] = []
            for key, total in self._count_total.items():
                for b in self._buckets:
                    out.append(
                        ("bucket", key + ((("le", str(b)),)), float(self._counts[key][b]))
                    )
                out.append(("bucket", key + ((("le", "+Inf"),)), float(total)))
                out.append(("sum", key, self._sums[key]))
                out.append(("count", key, float(total)))
            return out


class MetricsRegistry:
    def __init__(self, prefix: str = "llm_gateway") -> None:
        self._prefix = prefix
        self._metrics: list[tuple[str, str, str, object]] = []  # name, type, help, obj
        self._lock = threading.Lock()

    def counter(self, name: str, help_text: str) -> _Counter:
        c = _Counter()
        with self._lock:
            self._metrics.append((f"{self._prefix}_{name}", "counter", help_text, c))
        return c

    def gauge(self, name: str, help_text: str) -> _Gauge:
        g = _Gauge()
        with self._lock:
            self._metrics.append((f"{self._prefix}_{name}", "gauge", help_text, g))
        return g

    def histogram(
        self,
        name: str,
        help_text: str,
        buckets: tuple[float, ...] = _DEFAULT_BUCKETS,
    ) -> _Histogram:
        h = _Histogram(buckets)
        with self._lock:
            self._metrics.append((f"{self._prefix}_{name}", "histogram", help_text, h))
        return h

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for full_name, mtype, help_text, obj in self._metrics:
                lines.append(f"# HELP {full_name} {help_text}")
                lines.append(f"# TYPE {full_name} {mtype}")
                if isinstance(obj, _Histogram):
                    for suffix, key, value in obj.samples():
                        name = full_name if suffix == "count" else f"{full_name}_{suffix}"
                        lines.append(f"{name}{_format_labels(key)} {_fmt(value)}")
                else:
                    for key, value in obj.samples():
                        lines.append(f"{full_name}{_format_labels(key)} {_fmt(value)}")
        return _NL.join(lines) + _NL


def _fmt(value: float) -> str:
    if value == float("inf"):
        return "+Inf"
    if value == float("-inf"):
        return "-Inf"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6g}"
