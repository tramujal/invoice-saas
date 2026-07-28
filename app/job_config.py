"""Typed, environment-driven configuration for the durable job worker --
one place, matching this codebase's existing convention of reading
`os.environ` once at call time with a documented, safe default (see
app.rate_limit.get_client_ip's TRUSTED_PROXY_HOPS for the precedent this
mirrors). Never hardcoded across app.jobs.worker/app.services
.background_jobs -- every tunable lives here.
"""

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class WorkerConfig:
    enabled: bool
    queue: str
    poll_interval_seconds: float
    idle_backoff_max_seconds: float
    lease_duration_seconds: float
    batch_size: int
    shutdown_grace_seconds: float


def load_worker_config() -> WorkerConfig:
    """Reads env vars fresh on every call (never cached at import time) --
    matches app.rate_limit.get_client_ip's own rationale: makes tests
    that monkeypatch os.environ behave predictably, and avoids import-
    order surprises."""
    return WorkerConfig(
        enabled=_env_bool("WORKER_ENABLED", True),
        queue=os.environ.get("WORKER_QUEUE", "default"),
        # How often the worker checks for new work when it's finding
        # nothing -- the FLOOR of the idle backoff below, not a fixed
        # interval: a busy queue is polled again immediately (no sleep at
        # all) once any job was just claimed, so this only governs the
        # empty-queue steady state.
        poll_interval_seconds=_env_float("WORKER_POLL_INTERVAL_SECONDS", 2.0),
        # Idle backoff grows from poll_interval_seconds up to this ceiling
        # the longer the queue stays empty, so a permanently-idle worker
        # doesn't hammer the database every 2 seconds forever.
        idle_backoff_max_seconds=_env_float("WORKER_IDLE_BACKOFF_MAX_SECONDS", 30.0),
        lease_duration_seconds=_env_float("WORKER_LEASE_DURATION_SECONDS", 300.0),
        batch_size=_env_int("WORKER_BATCH_SIZE", 5),
        # How long SIGTERM handling waits for an in-flight job to finish
        # naturally before the process exits anyway -- see
        # app.jobs.worker's own docstring on why a hard mid-HTTP-request
        # kill isn't otherwise safely achievable.
        shutdown_grace_seconds=_env_float("WORKER_SHUTDOWN_GRACE_SECONDS", 30.0),
    )
