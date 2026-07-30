"""In-process, thread-safe HTTP request counters -- the honest source of
truth Phase 21's platform dashboard reads for "average API latency" and
"error rate," which this app had genuinely no signal for before this
module existed (confirmed by audit: no request-timing middleware, no
persisted request log anywhere).

Storage
-------
A single in-process rolling window in a plain dict, guarded by a lock --
the exact same single-process, no-Redis rationale
app.rate_limit.InMemoryRateLimiterBackend already documents (this app
runs as one Render "free" web service, no shared cache exists). This is
deliberately NOT a persisted table: a per-request row would be a new,
unbounded-growth table for a metric that's only ever displayed as a
live rolling average, never queried historically -- exactly the kind of
"parallel data store nobody asked for" Phase 21 was told to avoid.

The window is time-bounded (`_WINDOW_SECONDS`), not count-bounded: old
samples age out automatically so the reported average/error-rate always
reflects "recently," matching what an operator actually wants from a
live dashboard, without unbounded memory growth.

A restart resets this to empty -- acceptable for a live operational
signal (unlike webhook/job delivery history, which must survive a
restart), and explicitly documented here rather than silently implied
to be durable.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass

_WINDOW_SECONDS = 900  # 15 minutes


@dataclass(frozen=True)
class RequestMetricsSnapshot:
    sample_count: int
    average_latency_ms: float | None
    error_rate_percent: float | None


class InMemoryRequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Each sample: (monotonic_timestamp, duration_ms, is_error) --
        # a deque so eviction from the old end is O(1), not O(n).
        self._samples: deque[tuple[float, float, bool]] = deque()

    def record(self, *, duration_ms: float, is_error: bool) -> None:
        now = time.monotonic()
        with self._lock:
            self._samples.append((now, duration_ms, is_error))
            self._evict_stale(now)

    def snapshot(self) -> RequestMetricsSnapshot:
        now = time.monotonic()
        with self._lock:
            self._evict_stale(now)
            samples = self._samples
            if not samples:
                return RequestMetricsSnapshot(
                    sample_count=0, average_latency_ms=None, error_rate_percent=None
                )
            total = len(samples)
            avg_latency = sum(duration for _, duration, _ in samples) / total
            error_count = sum(1 for _, _, is_error in samples if is_error)
            error_rate = (error_count / total) * 100
            return RequestMetricsSnapshot(
                sample_count=total,
                average_latency_ms=round(avg_latency, 2),
                error_rate_percent=round(error_rate, 2),
            )

    def _evict_stale(self, now: float) -> None:
        # Caller already holds self._lock.
        cutoff = now - _WINDOW_SECONDS
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()


_metrics = InMemoryRequestMetrics()


def record_request(*, duration_ms: float, is_error: bool) -> None:
    _metrics.record(duration_ms=duration_ms, is_error=is_error)


def get_snapshot() -> RequestMetricsSnapshot:
    return _metrics.snapshot()
