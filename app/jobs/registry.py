"""The closed, server-side-only vocabulary of background-job types this
worker will execute -- see app.job_type.JobType for the enum, and
app.jobs.handlers for the modules that call register_job() at import time.

A BackgroundJob row's `job_type` column is looked up here at claim time
(app.services.background_jobs) to find its JobDefinition: the Pydantic
schema its `payload` column must validate against, the handler function
that actually does the work, and the queue/priority/max_attempts/timeout
defaults for that job type. An unrecognized job_type string is never
`eval`'d, imported, or otherwise dynamically resolved -- it's a plain
dict lookup that raises UnknownJobTypeError, caught by the worker and
recorded as a permanent failure for that one row, never a crash.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.job_type import JobType
from app.models import BackgroundJob


class JobOutcome(str, Enum):
    succeeded = "succeeded"
    retry = "retry"
    permanently_failed = "permanently_failed"


@dataclass(frozen=True)
class JobResult:
    """What a handler returns to tell the worker how to transition the
    job row -- the handler itself never writes BackgroundJob.status
    directly (see app.services.background_jobs.complete_job, the one
    place that applies this result to the row's state machine)."""

    outcome: JobOutcome
    error_code: str | None = None
    error_message: str | None = None
    # Overrides the default now() availability for a `retry` outcome --
    # used by handlers whose own domain retry policy (e.g. the webhook
    # backoff schedule) already computed a more specific time than "retry
    # immediately." Ignored for succeeded/permanently_failed.
    retry_after: timedelta | None = None
    result_summary: str | None = None


HandlerFn = Callable[[Session, BackgroundJob, BaseModel], JobResult]


@dataclass(frozen=True)
class JobDefinition:
    job_type: JobType
    payload_schema: type[BaseModel]
    handler: HandlerFn
    queue: str = "default"
    priority: int = 0
    # Execution-attempt ceiling for THIS job row (crash/lease-expiry
    # resilience) -- see BackgroundJob.max_attempts's own docstring for
    # why this is deliberately independent of any job type's own domain
    # retry policy (e.g. the webhook delivery backoff schedule).
    max_attempts: int = 5
    timeout_seconds: int = 30
    organization_id_required: bool = True


class UnknownJobTypeError(Exception):
    """job_type doesn't match any registered JobDefinition -- never
    resolved dynamically, always a closed lookup against this registry."""


_REGISTRY: dict[str, JobDefinition] = {}
_bootstrapped = False


def register_job(definition: JobDefinition) -> None:
    """Called once per job type, at import time, by each module under
    app.jobs.handlers -- never by anything reading job_type from a
    database row or an untrusted source."""
    _REGISTRY[definition.job_type.value] = definition


def _ensure_bootstrapped() -> None:
    """Every real entry point (app/main.py, app/jobs/worker.py) already
    imports app.jobs.bootstrap explicitly and eagerly at startup, so a
    handler-module import error surfaces immediately at boot, not on the
    first webhook event -- this is a safety net, not the primary
    mechanism, for any OTHER standalone script that might end up calling
    enqueue_job/claim_jobs without having done that first (this app
    already has a precedent for standalone entry points outside
    app.main: app.jobs.send_due_invoice_reminders). A local import here
    (not a module-level one) is what avoids a circular import: registry
    -> bootstrap -> handlers -> app.services.background_jobs ->
    registry would be circular at MODULE-LOAD time, but calling this
    function only after both modules already finished their own
    top-level definitions is safe."""
    global _bootstrapped
    if _bootstrapped:
        return
    import app.jobs.bootstrap  # noqa: F401

    _bootstrapped = True


def get_job_definition(job_type: str) -> JobDefinition:
    _ensure_bootstrapped()
    try:
        return _REGISTRY[job_type]
    except KeyError:
        raise UnknownJobTypeError(job_type)


def is_registered(job_type: str) -> bool:
    return job_type in _REGISTRY
