"""Minimal in-memory TTL cache for the dashboard insights AI narration
layer -- deliberately as economical as app.rate_limit's
InMemoryRateLimiterBackend, which it directly mirrors: a single dict
guarded by one lock, no LRU eviction, a small probabilistic sweep to
bound memory. Resets on every deploy/restart; a multi-instance deployment
would need Redis (one new class implementing InsightsCacheBackend, one
construction-line change below -- no call site changes), exactly like
app.rate_limit's own documented upgrade path.

The DETERMINISTIC insight computation itself (app/insights/engine.py) is
NEVER cached -- it's cheap DB queries, always fresh. Only the optional AI
narration layered on top is cached here, since that's the only slow/paid
part. Cache keys include a data fingerprint (see fingerprint() below) so
a real data change invalidates the cache immediately, even before the
time-based TTL elapses.
"""

import hashlib
import json
import random
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from app.insights.models import Insight


@dataclass
class CacheEntry:
    status: str  # "ok" | "failed"
    insights: list[Insight] | None  # None when status == "failed"


class InsightsCacheBackend(Protocol):
    def get(self, key: str) -> CacheEntry | None: ...

    def set(self, key: str, entry: CacheEntry, ttl_seconds: float) -> None: ...


class InMemoryInsightsCacheBackend:
    _SWEEP_PROBABILITY = 0.02

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> (expires_at_monotonic, entry)
        self._entries: dict[str, tuple[float, CacheEntry]] = {}

    def get(self, key: str) -> CacheEntry | None:
        now = time.monotonic()
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            expires_at, entry = item
            if now >= expires_at:
                del self._entries[key]
                return None
            return entry

    def set(self, key: str, entry: CacheEntry, ttl_seconds: float) -> None:
        now = time.monotonic()
        with self._lock:
            self._entries[key] = (now + ttl_seconds, entry)
            self._maybe_sweep(now)

    def _maybe_sweep(self, now: float) -> None:
        # Caller already holds self._lock.
        if random.random() > self._SWEEP_PROBABILITY:
            return
        stale = [k for k, (expires_at, _entry) in self._entries.items() if now >= expires_at]
        for k in stale:
            del self._entries[k]


# The one line a future Redis-backed implementation needs to replace.
_backend: InsightsCacheBackend = InMemoryInsightsCacheBackend()


def fingerprint(insights: list[Insight]) -> str:
    """Cheap hash of (id, metric.value, metric.percentage) tuples the
    deterministic pass just produced in memory -- no extra query. Changes
    the instant underlying data actually changes, so a cached narration is
    treated as stale immediately, even before its time-based TTL elapses;
    reused whenever nothing has actually changed."""
    parts = sorted(
        (
            insight.id,
            str(insight.metric.value)
            if insight.metric and insight.metric.value is not None
            else "",
            str(insight.metric.percentage)
            if insight.metric and insight.metric.percentage is not None
            else "",
        )
        for insight in insights
    )
    raw = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_key(organization_id: str, language: str, fp: str) -> str:
    return f"{organization_id}:{language}:{fp}"


def get_cached(organization_id: str, language: str, fp: str) -> CacheEntry | None:
    return _backend.get(_cache_key(organization_id, language, fp))


def set_cached(
    organization_id: str, language: str, fp: str, entry: CacheEntry, ttl_seconds: float
) -> None:
    _backend.set(_cache_key(organization_id, language, fp), entry, ttl_seconds)
