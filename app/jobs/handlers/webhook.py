"""The two webhook job handlers -- registered into app.jobs.registry at
import time (see this package's own __init__.py). Neither handler ever
performs delivery logic itself: both call app.services.webhook_deliveries
.deliver_webhook (completely unchanged from Phase 15B) and translate its
result into a JobResult.

A crucial distinction this module exists to make precisely: a job
"succeeding" (JobOutcome.succeeded, the only outcome either handler here
ever returns under normal operation) means "this job ROW finished running
without crashing" -- it says nothing about whether the underlying HTTP
webhook delivery itself succeeded. That business-level outcome lives
entirely on the WebhookDelivery row (status/response_status_code/
error_message), never on the BackgroundJob row. When an HTTP attempt
fails but is retryable and the webhook's own attempt ceiling
(MAX_WEBHOOK_DELIVERY_ATTEMPTS) isn't reached yet, the handler itself
enqueues the next webhook.retry job as part of doing its job correctly --
it still reports JobOutcome.succeeded, because it did exactly what it was
asked to do. JobOutcome.retry/permanently_failed (see
app.services.background_jobs.complete_job) are reserved for genuine job-
execution problems (an unhandled exception, a missing referenced row) --
see app.jobs.worker's own execution wrapper for where an uncaught
exception from a handler is turned into JobOutcome.retry automatically.
"""

import logging

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.job_type import JobType
from app.jobs.registry import JobDefinition, JobOutcome, JobResult, register_job
from app.models import BackgroundJob, WebhookDelivery
from app.services.background_jobs import enqueue_job
from app.services.webhook_deliveries import (
    MAX_WEBHOOK_DELIVERY_ATTEMPTS,
    create_next_delivery_attempt,
    deliver_webhook,
    is_retryable_failure,
)
from app.webhook_delivery_status import WebhookDeliveryStatus

logger = logging.getLogger(__name__)


class WebhookDeliverPayload(BaseModel):
    delivery_id: str


class WebhookRetryPayload(BaseModel):
    failed_delivery_id: str


def _finish(db: Session, delivery: WebhookDelivery) -> JobResult:
    """Shared tail end of both handlers: inspect the just-attempted
    delivery, and if it failed but is retryable and the chain hasn't hit
    its ceiling, enqueue the next webhook.retry job right here (this IS
    the "schedule a new BackgroundJob on retryable failure" step -- see
    this module's own docstring for why that's still a job-level
    success)."""
    if delivery.status == WebhookDeliveryStatus.succeeded.value:
        return JobResult(
            outcome=JobOutcome.succeeded,
            result_summary=f"delivered status_code={delivery.response_status_code} attempt={delivery.attempt_number}",
        )

    if delivery.attempt_number < MAX_WEBHOOK_DELIVERY_ATTEMPTS and is_retryable_failure(delivery):
        enqueue_job(
            db,
            job_type=JobType.webhook_retry,
            payload={"failed_delivery_id": delivery.id},
            organization_id=delivery.organization_id,
            available_at=delivery.next_retry_at,
            idempotency_key=(
                f"webhook-retry:{delivery.event_id}:{delivery.endpoint_id}:{delivery.attempt_number + 1}"
            ),
        )
        db.commit()
        return JobResult(
            outcome=JobOutcome.succeeded,
            result_summary=f"retry_scheduled next_attempt={delivery.attempt_number + 1} at={delivery.next_retry_at}",
        )

    # Non-retryable, or the webhook delivery chain's own ceiling is
    # reached -- terminal for this event+endpoint pair. Still a
    # successful JOB execution (it correctly recorded a terminal
    # outcome), never a job-level failure.
    return JobResult(
        outcome=JobOutcome.succeeded,
        result_summary=(
            f"terminal_failure status_code={delivery.response_status_code} "
            f"attempt={delivery.attempt_number} error={delivery.error_message}"
        ),
    )


def handle_webhook_deliver(db: Session, job: BackgroundJob, payload: WebhookDeliverPayload) -> JobResult:
    delivery = deliver_webhook(db, payload.delivery_id)
    return _finish(db, delivery)


def handle_webhook_retry(db: Session, job: BackgroundJob, payload: WebhookRetryPayload) -> JobResult:
    failed = db.get(WebhookDelivery, payload.failed_delivery_id)
    if failed is None:
        # The referenced delivery row is gone -- unreachable in normal
        # operation (WebhookDelivery rows are never deleted), but this is
        # a genuine job-execution problem, not a webhook outcome, so it's
        # reported as such rather than silently swallowed.
        return JobResult(
            outcome=JobOutcome.permanently_failed,
            error_code="delivery_missing",
            error_message="Referenced WebhookDelivery no longer exists.",
        )
    if failed.status == WebhookDeliveryStatus.succeeded.value:
        # Already resolved -- e.g. an organization manually resent this
        # exact chain before the scheduled retry became due. Nothing left
        # to do; a genuine no-op, not an error.
        return JobResult(outcome=JobOutcome.succeeded, result_summary="already_succeeded_before_retry_due")

    next_delivery = create_next_delivery_attempt(db, failed)
    if next_delivery is None:
        # Endpoint was disabled/archived since this retry was scheduled --
        # see create_next_delivery_attempt's own docstring. Terminal for
        # this chain; still a successful job execution.
        db.commit()
        return JobResult(
            outcome=JobOutcome.succeeded,
            result_summary="terminal_endpoint_unavailable",
        )

    delivered = deliver_webhook(db, next_delivery.id)
    return _finish(db, delivered)


register_job(
    JobDefinition(
        job_type=JobType.webhook_deliver,
        payload_schema=WebhookDeliverPayload,
        handler=handle_webhook_deliver,
        queue="default",
        priority=0,
        max_attempts=5,
        timeout_seconds=30,
        organization_id_required=True,
    )
)

register_job(
    JobDefinition(
        job_type=JobType.webhook_retry,
        payload_schema=WebhookRetryPayload,
        handler=handle_webhook_retry,
        queue="default",
        priority=0,
        max_attempts=5,
        timeout_seconds=30,
        organization_id_required=True,
    )
)
