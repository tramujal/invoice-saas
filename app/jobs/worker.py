"""Standalone durable job worker -- `python -m app.jobs.worker`.

Never started from the FastAPI process: app/main.py imports
app.jobs.bootstrap (a plain, side-effect-free import that only populates
the job-type registry, see that module's docstring) but never this
module, and never calls run_worker(). The web process and this worker
process are independently deployable -- see render.yaml's `worker`
service block and docker-compose.yml's `worker` service for how they run
as two separate processes/containers in every real deployment target this
app has.

Polling, not a busy-loop: an empty queue backs off from
WORKER_POLL_INTERVAL_SECONDS up to WORKER_IDLE_BACKOFF_MAX_SECONDS
(exponential, +/-50% jitter so many idle workers don't all wake up in
lockstep), reset to the floor the instant any job is found. A non-empty
claim result loops again immediately with no sleep, to drain a backlog as
fast as the database allows.

Graceful shutdown: SIGTERM/SIGINT set a flag checked between claim
batches -- the worker stops claiming NEW work immediately but always
finishes any job(s) already claimed in the current batch before exiting
(their lease is real; another worker can't safely claim them mid-flight
anyway). A currently in-flight outbound HTTP request (see
app.services.webhook_deliveries.deliver_webhook) is never hard-
interrupted -- there is no safe way to abort a `requests.post` call
partway through and know whether the receiver processed it, so this
worker always lets the current HTTP attempt finish naturally rather than
risk an ambiguous half-sent request. This is a deliberate, documented
limitation, not an oversight -- see WORKER_SHUTDOWN_GRACE_SECONDS (app.
job_config) for the operator-facing knob acknowledging this, even though
this worker doesn't currently enforce a hard timeout against it (see
this module's own docstring in app.jobs.registry.JobDefinition
.timeout_seconds for the same honestly-documented gap: process-level
hard timeout termination is not implemented in Phase 15C).
"""

import logging
import random
import signal
import time
from datetime import timedelta
from types import FrameType

import app.jobs.bootstrap  # noqa: F401 -- populate the registry before claiming anything
from app.database import SessionLocal
from app.job_config import load_worker_config
from app.services.background_jobs import (
    claim_jobs,
    generate_worker_id,
    recover_abandoned_jobs,
    run_claimed_job,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_shutdown_requested = False


def _handle_shutdown_signal(signum: int, _frame: FrameType | None) -> None:
    global _shutdown_requested
    logger.info("worker: received shutdown signal=%s -- will stop claiming new work", signum)
    _shutdown_requested = True


def _is_shutdown_requested() -> bool:
    return _shutdown_requested


def run_worker(*, max_iterations: int | None = None, stop_check=_is_shutdown_requested) -> None:
    """The main polling loop. `max_iterations`/`stop_check` exist only
    for tests -- production callers (main() below) never pass either, so
    the loop runs until a real shutdown signal is received."""
    config = load_worker_config()
    if not config.enabled:
        logger.info("worker: WORKER_ENABLED=false -- exiting immediately without claiming any work")
        return

    worker_id = generate_worker_id()
    lease_duration = timedelta(seconds=config.lease_duration_seconds)
    logger.info(
        "worker: started worker_id=%s queue=%s batch_size=%s lease_duration_seconds=%s",
        worker_id,
        config.queue,
        config.batch_size,
        config.lease_duration_seconds,
    )

    idle_streak = 0
    iterations = 0
    try:
        while not stop_check():
            db = SessionLocal()
            try:
                recovered = recover_abandoned_jobs(db)
                if recovered:
                    logger.info("worker: recovered %d abandoned job(s)", recovered)

                jobs = claim_jobs(
                    db,
                    worker_id=worker_id,
                    queue=config.queue,
                    batch_size=config.batch_size,
                    lease_duration=lease_duration,
                )

                if not jobs:
                    idle_streak += 1
                    backoff = min(
                        config.poll_interval_seconds * (2 ** min(idle_streak, 8)),
                        config.idle_backoff_max_seconds,
                    )
                    jittered = backoff * (0.5 + random.random())  # 0.5x - 1.5x
                    time.sleep(min(jittered, config.idle_backoff_max_seconds))
                else:
                    idle_streak = 0
                    for job in jobs:
                        started = time.monotonic()
                        result = run_claimed_job(db, job)
                        duration_ms = int((time.monotonic() - started) * 1000)
                        logger.info(
                            "worker: job finished job_id=%s job_type=%s outcome=%s attempts=%s duration_ms=%s",
                            job.id,
                            job.job_type,
                            result.outcome.value,
                            job.attempts,
                            duration_ms,
                        )
            finally:
                db.close()

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
    finally:
        logger.info("worker: shut down cleanly worker_id=%s", worker_id)


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    run_worker()


if __name__ == "__main__":
    main()
