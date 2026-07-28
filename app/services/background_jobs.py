"""Durable job queue: enqueue, claim, lease, and the state-machine
transitions applied when a job finishes running -- this module IS the
durable dispatch mechanism Phase 15C replaces Phase 15B's
Session.after_commit + ThreadPoolExecutor chain with (see
app.services.webhook_dispatch's removal, documented in
app.services.webhook_events and app.services.webhook_deliveries).

Transaction model
------------------
`enqueue_job` never commits -- it's designed to be called from inside an
already-open business transaction (see app.services.webhook_events
.record_webhook_event), so a rolled-back business mutation takes its job
row down with it, exactly like WebhookEvent/WebhookDelivery.

`claim_jobs`, `recover_abandoned_jobs`, and `complete_job`, by contrast,
each own and commit their own short transaction -- they're called by the
worker's polling loop (app.jobs.worker), which has no enclosing business
transaction to participate in; each is its own atomic operation against
the database, matching this codebase's existing "service functions
commit next to their own mutation" convention (see
app.services.webhook_deliveries.deliver_webhook for the identical
precedent this file's claim/execute/complete cycle mirrors).

Claiming
--------
Two layers, deliberately not just one:
  1. On Postgres, `SELECT ... FOR UPDATE SKIP LOCKED` picks a low-
     contention candidate -- an optimization that lets many workers scan
     for work concurrently without piling up behind each other's locks.
  2. An atomic conditional `UPDATE ... WHERE status IN (...) AND
     available_at <= now()`, checked by rowcount, is what actually
     GUARANTEES only one worker wins the claim -- this is what's safe on
     SQLite too (which silently no-ops `FOR UPDATE SKIP LOCKED`, verified
     empirically during this phase's architecture audit): SQLite's own
     global single-writer serialization backs the conditional UPDATE's
     correctness there, even though it proves nothing about real
     concurrent Postgres locking. True concurrent-claim safety is only
     ever asserted against Postgres -- see tests/test_background_jobs.py
     for the SQLite-only state-machine tests vs. the Postgres-gated
     concurrency test.
"""

import json
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.job_status import JobStatus
from app.job_type import JobType
from app.jobs.registry import JobOutcome, JobResult, UnknownJobTypeError, get_job_definition
from app.models import BackgroundJob

logger = logging.getLogger(__name__)

DEFAULT_LEASE_DURATION = timedelta(minutes=5)

# Generic backoff for JobOutcome.retry -- a job-EXECUTION failure (an
# unhandled exception, a malformed-at-claim-time situation), never the
# webhook delivery backoff schedule (see
# app.services.webhook_deliveries._RETRY_BACKOFF_SCHEDULE, a completely
# separate, domain-level concept). Short and fast: this exists to survive
# a transient DB hiccup or a brief crash-loop, not to wait out a
# third-party outage.
_JOB_RETRY_BACKOFF = [
    timedelta(seconds=10),
    timedelta(seconds=30),
    timedelta(minutes=1),
    timedelta(minutes=5),
]


class InvalidJobPayloadError(Exception):
    """payload doesn't validate against the registered JobDefinition's
    schema for this job_type."""


def generate_worker_id() -> str:
    """A unique-enough identity for one worker process's lifetime --
    hostname + pid + a random suffix (so two workers on the same host,
    or a fast-restarting single worker, never collide). Never treated as
    a source of authorization or ownership on its own -- lease_expires_at
    is what actually determines whether a claimed_by value is still
    meaningful; see recover_abandoned_jobs."""
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True)
    # columns; Postgres returns aware ones -- same normalization every
    # other file in this codebase comparing a DB-read datetime against
    # datetime.now(timezone.utc) already duplicates locally (see
    # app.services.organization_api_keys._aware for the precedent).
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def enqueue_job(
    db: Session,
    *,
    job_type: JobType,
    payload: dict,
    organization_id: str | None,
    available_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> BackgroundJob | None:
    """Adds (never commits) one BackgroundJob row -- the caller's own
    existing commit (already present at the exact call site for whatever
    business mutation this job is for) is what makes the enqueue durable,
    the identical contract app.services.webhook_events.record_webhook_event
    already established for WebhookEvent/WebhookDelivery.

    Returns None -- adding nothing -- if `idempotency_key` is given and
    already belongs to an existing row: the logical job already exists,
    so this is a safe, silent no-op duplicate-enqueue rather than an
    error (see app.job_type... no unique-constraint violation is ever
    raised to the caller for this expected case). Raises
    UnknownJobTypeError for an unregistered job_type (see
    app.jobs.registry) and InvalidJobPayloadError if `payload` doesn't
    validate against that job type's own schema -- both are programming
    errors, never a possible outcome of untrusted input, since job_type
    is always a JobType enum member here, never a caller-supplied string.
    """
    definition = get_job_definition(job_type.value)
    if definition.organization_id_required and organization_id is None:
        raise ValueError(f"job_type {job_type.value!r} requires a non-null organization_id")

    try:
        definition.payload_schema(**payload)
    except ValidationError as exc:
        raise InvalidJobPayloadError(f"{job_type.value}: {exc}") from exc

    if idempotency_key is not None:
        existing_id = db.scalar(
            select(BackgroundJob.id).where(BackgroundJob.idempotency_key == idempotency_key)
        )
        if existing_id is not None:
            logger.info(
                "background_jobs: enqueue skipped, idempotency_key already exists "
                "job_type=%s idempotency_key=%s existing_job_id=%s",
                job_type.value,
                idempotency_key,
                existing_id,
            )
            return None

    job = BackgroundJob(
        organization_id=organization_id,
        job_type=job_type.value,
        payload=json.dumps(payload),
        status=JobStatus.pending.value,
        queue=definition.queue,
        priority=definition.priority,
        max_attempts=definition.max_attempts,
        available_at=available_at or datetime.now(timezone.utc),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    logger.info(
        "background_jobs: enqueued job_id=%s job_type=%s organization_id=%s queue=%s available_at=%s",
        job.id,
        job_type.value,
        organization_id,
        definition.queue,
        job.available_at.isoformat(),
    )
    return job


def claim_jobs(
    db: Session,
    *,
    worker_id: str,
    queue: str = "default",
    batch_size: int = 1,
    lease_duration: timedelta = DEFAULT_LEASE_DURATION,
) -> list[BackgroundJob]:
    """Atomically claims up to `batch_size` available jobs for `queue`,
    setting status=claimed, claimed_at, claimed_by, lease_expires_at.
    Each candidate is claimed with its own conditional UPDATE + rowcount
    check (see module docstring) -- a candidate another worker claimed a
    moment earlier is silently skipped, never stolen, never double-owned.
    """
    now = datetime.now(timezone.utc)
    is_postgres = db.bind.dialect.name == "postgresql"

    candidate_stmt = (
        select(BackgroundJob.id)
        .where(
            BackgroundJob.status.in_([JobStatus.pending.value, JobStatus.retry_scheduled.value]),
            BackgroundJob.queue == queue,
            BackgroundJob.available_at <= now,
        )
        .order_by(BackgroundJob.priority.desc(), BackgroundJob.available_at.asc())
        .limit(max(batch_size * 3, batch_size))  # over-fetch candidates in case some lose the race
    )
    if is_postgres:
        candidate_stmt = candidate_stmt.with_for_update(skip_locked=True)

    candidate_ids = db.scalars(candidate_stmt).all()

    claimed: list[BackgroundJob] = []
    lease_expires_at = now + lease_duration
    for candidate_id in candidate_ids:
        if len(claimed) >= batch_size:
            break
        result = db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == candidate_id,
                BackgroundJob.status.in_([JobStatus.pending.value, JobStatus.retry_scheduled.value]),
                BackgroundJob.available_at <= now,
            )
            .values(
                status=JobStatus.claimed.value,
                claimed_at=now,
                claimed_by=worker_id,
                lease_expires_at=lease_expires_at,
                updated_at=now,
            )
            # Never synchronize in-memory ORM objects against this
            # statement's WHERE clause: SQLAlchemy's default "evaluate"
            # strategy re-checks the WHERE clause in pure Python against
            # any matching object already in this session's identity map
            # (e.g. the very job enqueue_job just returned), and SQLite
            # returns naive datetimes even for DateTime(timezone=True)
            # columns while `now` here is timezone-aware -- comparing
            # them raises TypeError. We always re-fetch the claimed row
            # fresh via db.get() below anyway, so no session sync is
            # ever needed here.
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            db.commit()
            job = db.get(BackgroundJob, candidate_id)
            if job is not None:
                claimed.append(job)
                logger.info(
                    "background_jobs: claimed job_id=%s job_type=%s worker_id=%s lease_expires_at=%s",
                    job.id,
                    job.job_type,
                    worker_id,
                    lease_expires_at.isoformat(),
                )
        else:
            db.rollback()  # lost the race for this one -- no changes were made, just release the tx

    return claimed


def mark_started(db: Session, job: BackgroundJob) -> None:
    """claimed -> running, right before the handler is actually
    invoked -- a separate step from claiming so a job stuck in `claimed`
    with an expired lease (crash between claim and handler start) is
    distinguishable in principle from one that crashed mid-execution,
    for operator debugging, even though both recover identically today
    (see recover_abandoned_jobs)."""
    now = datetime.now(timezone.utc)
    job.status = JobStatus.running.value
    job.started_at = now
    job.updated_at = now
    db.commit()


def complete_job(db: Session, job: BackgroundJob, result: JobResult) -> None:
    """Applies a handler's JobResult to the job row's state machine --
    the ONE place any job's status is ever set to a terminal or
    retry-scheduled value after execution. Always clears claimed_by/
    lease_expires_at: once a run has concluded (however it concluded),
    this row is no longer actively owned by any worker."""
    now = datetime.now(timezone.utc)
    job.claimed_by = None
    job.lease_expires_at = None
    job.updated_at = now

    if result.outcome == JobOutcome.succeeded:
        job.status = JobStatus.succeeded.value
        job.completed_at = now
        job.result_summary = (result.result_summary or "")[:500] or None
        job.last_error_code = None
        job.last_error_message = None
        db.commit()
        logger.info("background_jobs: succeeded job_id=%s job_type=%s", job.id, job.job_type)
        return

    job.attempts += 1
    job.last_error_code = (result.error_code or "")[:64] or None
    job.last_error_message = (result.error_message or "")[:1000] or None

    if result.outcome == JobOutcome.permanently_failed or job.attempts >= job.max_attempts:
        job.status = JobStatus.permanently_failed.value
        job.failed_at = now
        db.commit()
        logger.warning(
            "background_jobs: permanently_failed job_id=%s job_type=%s attempts=%s error_code=%s",
            job.id,
            job.job_type,
            job.attempts,
            job.last_error_code,
        )
        return

    delay = result.retry_after or _JOB_RETRY_BACKOFF[min(job.attempts - 1, len(_JOB_RETRY_BACKOFF) - 1)]
    job.status = JobStatus.retry_scheduled.value
    job.available_at = now + delay
    db.commit()
    logger.warning(
        "background_jobs: retry_scheduled job_id=%s job_type=%s attempts=%s available_at=%s error_code=%s",
        job.id,
        job.job_type,
        job.attempts,
        job.available_at.isoformat(),
        job.last_error_code,
    )


def run_claimed_job(db: Session, job: BackgroundJob) -> JobResult:
    """Executes one already-claimed job end to end: marks it `running`,
    resolves its JobDefinition and validates its payload, invokes the
    handler, and applies the resulting JobResult via complete_job. This
    is the exact sequence app.jobs.worker's polling loop runs per claimed
    job, factored out here so tests can exercise a single job's execution
    without spinning up the whole worker loop / signal-handling
    machinery.

    An unknown job_type or a payload that fails schema validation is
    treated as permanently_failed immediately, never retried -- retrying
    can't fix "this row references a job type/shape that doesn't exist,"
    so retrying would just waste attempts. Any OTHER exception raised by
    the handler itself (the only case a well-behaved handler should never
    itself raise for; see app.jobs.handlers.webhook's own docstring on
    reserving JobOutcome.retry/permanently_failed for genuine execution
    problems) is caught here and treated as a generic retryable job-
    execution failure, up to this job row's own max_attempts.
    """
    mark_started(db, job)

    try:
        definition = get_job_definition(job.job_type)
    except UnknownJobTypeError as exc:
        result = JobResult(
            outcome=JobOutcome.permanently_failed, error_code="unknown_job_type", error_message=str(exc)
        )
        complete_job(db, job, result)
        return result

    try:
        payload = definition.payload_schema(**json.loads(job.payload))
    except (ValidationError, ValueError, TypeError) as exc:
        result = JobResult(
            outcome=JobOutcome.permanently_failed,
            error_code="invalid_payload",
            error_message=str(exc)[:1000],
        )
        complete_job(db, job, result)
        return result

    try:
        result = definition.handler(db, job, payload)
    except Exception as exc:
        logger.exception(
            "background_jobs: handler raised an unhandled exception job_id=%s job_type=%s",
            job.id,
            job.job_type,
        )
        result = JobResult(
            outcome=JobOutcome.retry, error_code=type(exc).__name__, error_message=str(exc)[:1000]
        )

    complete_job(db, job, result)
    return result


def recover_abandoned_jobs(db: Session, *, recovery_delay: timedelta = timedelta(seconds=5)) -> int:
    """Returns a job to `pending` (incrementing `attempts`, or to
    `permanently_failed` if that exhausts max_attempts) whenever its
    lease has expired while it was still `claimed`/`running` -- the only
    recovery mechanism for a worker that crashed, was killed, or lost its
    database connection mid-job. Safe to call from multiple workers
    concurrently: this is one plain conditional UPDATE, so a job already
    recovered by another worker's sweep a moment earlier simply doesn't
    match the WHERE clause anymore.

    `recovery_delay` (default 5s) is added to `available_at` for
    recovered-but-not-exhausted jobs specifically to avoid hot-looping a
    job that fails instantly every time it's claimed (see Step 15's own
    explicit "avoid immediate hot-looping" requirement) -- small enough
    to never meaningfully delay legitimate recovery.
    """
    now = datetime.now(timezone.utc)
    next_available_at = now + recovery_delay
    result = db.execute(
        text(
            "UPDATE background_jobs SET "
            "attempts = attempts + 1, "
            "status = CASE WHEN attempts + 1 >= max_attempts THEN :permanently_failed ELSE :pending END, "
            "available_at = CASE WHEN attempts + 1 >= max_attempts THEN available_at ELSE :next_available_at END, "
            "failed_at = CASE WHEN attempts + 1 >= max_attempts THEN :now ELSE failed_at END, "
            "last_error_code = 'lease_expired', "
            "claimed_by = NULL, "
            "lease_expires_at = NULL, "
            "updated_at = :now "
            "WHERE status IN (:claimed, :running) AND lease_expires_at < :now"
        ),
        {
            "permanently_failed": JobStatus.permanently_failed.value,
            "pending": JobStatus.pending.value,
            "next_available_at": next_available_at,
            "now": now,
            "claimed": JobStatus.claimed.value,
            "running": JobStatus.running.value,
        },
    )
    db.commit()
    if result.rowcount:
        logger.warning("background_jobs: recovered %d abandoned job(s)", result.rowcount)
    return result.rowcount
