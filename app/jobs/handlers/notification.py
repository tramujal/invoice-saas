"""The notification.email job handler -- registered into app.jobs.registry
at import time (see this package's own __init__.py). Mirrors
app.jobs.handlers.webhook's exact shape: the payload carries only an id
(never rendered text), and the handler re-fetches everything it needs from
the database, exactly like WebhookDeliverPayload/handle_webhook_deliver.

The Notification row referenced here (see app.models.Notification) is
already the single, frozen, point-in-time snapshot of what should be said
-- created once, synchronously, in app.notifications.service.emit_event,
in the same transaction as the business mutation that caused it. This
handler never re-renders or re-derives that text; it only reads it back
and hands it to the configured EmailSender (see app.email.factory), which
is itself provider-independent (Resend today).
"""

import logging

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.email.base import EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.jobs.registry import JobDefinition, JobOutcome, JobResult, register_job
from app.job_type import JobType
from app.models import BackgroundJob, Notification, User

logger = logging.getLogger(__name__)


class NotificationEmailPayload(BaseModel):
    notification_id: str


def handle_notification_email(
    db: Session, job: BackgroundJob, payload: NotificationEmailPayload
) -> JobResult:
    notification = db.get(Notification, payload.notification_id)
    if notification is None:
        # Unreachable in normal operation (Notification rows are never
        # deleted), but a genuine job-execution problem if it ever
        # happens, not a business outcome -- mirrors
        # handle_webhook_retry's own "referenced row is gone" handling.
        return JobResult(
            outcome=JobOutcome.permanently_failed,
            error_code="notification_missing",
            error_message="Referenced Notification no longer exists.",
        )

    user = db.get(User, notification.user_id)
    if user is None or not user.email_verified:
        # A recipient who was removed from the org, or never verified
        # their email, after this job was enqueued but before it ran --
        # not an error, just nothing left to correctly do.
        return JobResult(outcome=JobOutcome.succeeded, result_summary="skipped_unverified_or_missing_user")

    try:
        sender = get_email_sender()
    except HTTPException as exc:
        # Email disabled/not configured -- a platform-config condition,
        # not a transient failure, so retrying on the generic job backoff
        # would never fix it. Matches this app's existing "swallow, don't
        # retry" treatment of the same condition in app.routers.invitations.
        return JobResult(
            outcome=JobOutcome.permanently_failed,
            error_code="email_not_configured",
            error_message=str(exc.detail),
        )

    message = EmailMessage(
        to=user.email,
        subject=notification.title,
        text_body=notification.body,
        attachments=[],
    )
    try:
        sender.send(message)
    except EmailSendError as exc:
        # A genuine provider-level send failure (network, rate limit,
        # rejected recipient) -- retryable via the generic job backoff,
        # bounded by this job type's own max_attempts.
        return JobResult(outcome=JobOutcome.retry, error_message=str(exc))

    return JobResult(outcome=JobOutcome.succeeded, result_summary=f"sent to={user.email}")


register_job(
    JobDefinition(
        job_type=JobType.notification_email,
        payload_schema=NotificationEmailPayload,
        handler=handle_notification_email,
        queue="default",
        priority=0,
        max_attempts=5,
        timeout_seconds=30,
        organization_id_required=True,
    )
)
