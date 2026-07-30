"""Usage metrics: AI requests, API key activity, webhook deliveries,
background jobs, emails sent, and notifications created -- every count
here reads directly from the one table that already owns each fact
(AssistantAction, OrganizationApiKey, WebhookDelivery, BackgroundJob,
Notification). See app.platform_metrics's package docstring for why
this module never duplicates the write-side logic that produces these
rows.

"API key usage" is honestly scoped to what this app actually tracks:
OrganizationApiKey has a `last_used_at` timestamp (most-recent-use
only), never a per-request counter -- there is no request-log table to
sum a true request volume from (confirmed absent by audit). Reporting a
fabricated request count would violate "single source of truth"; this
module reports active-key counts and recency instead.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assistant_action_status import AssistantActionStatus
from app.job_status import JobStatus
from app.job_type import JobType
from app.models import AssistantAction, BackgroundJob, Notification, OrganizationApiKey, WebhookDelivery
from app.webhook_delivery_status import WebhookDeliveryStatus

_WINDOW_DAYS = 30


@dataclass(frozen=True)
class UsageMetrics:
    ai_requests_30d: int
    api_keys_active: int
    api_keys_used_7d: int
    webhook_deliveries_30d: int
    webhook_deliveries_succeeded_30d: int
    webhook_deliveries_failed_30d: int
    background_jobs_30d: int
    background_jobs_succeeded_30d: int
    background_jobs_failed_30d: int
    emails_sent_30d: int
    notifications_created_30d: int


def compute_usage_metrics(db: Session) -> UsageMetrics:
    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=_WINDOW_DAYS)
    since_7d = now - timedelta(days=7)

    ai_requests_30d = (
        db.scalar(
            select(func.count())
            .select_from(AssistantAction)
            .where(
                AssistantAction.status == AssistantActionStatus.executed.value,
                AssistantAction.executed_at >= since_30d,
            )
        )
        or 0
    )

    # Mirrors app.api_key_status.get_effective_api_key_status's own
    # revoked_at/expires_at definition of "active," at the SQL level
    # rather than loading every row into Python -- same rule, no
    # duplicated business logic, just a read-only aggregate filter.
    api_keys_active = (
        db.scalar(
            select(func.count())
            .select_from(OrganizationApiKey)
            .where(
                OrganizationApiKey.revoked_at.is_(None),
                (OrganizationApiKey.expires_at.is_(None)) | (OrganizationApiKey.expires_at > now),
            )
        )
        or 0
    )
    api_keys_used_7d = (
        db.scalar(
            select(func.count())
            .select_from(OrganizationApiKey)
            .where(OrganizationApiKey.last_used_at >= since_7d)
        )
        or 0
    )

    webhook_deliveries_30d = (
        db.scalar(select(func.count()).select_from(WebhookDelivery).where(WebhookDelivery.created_at >= since_30d))
        or 0
    )
    webhook_deliveries_succeeded_30d = (
        db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(
                WebhookDelivery.created_at >= since_30d,
                WebhookDelivery.status == WebhookDeliveryStatus.succeeded.value,
            )
        )
        or 0
    )
    webhook_deliveries_failed_30d = (
        db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(
                WebhookDelivery.created_at >= since_30d,
                WebhookDelivery.status == WebhookDeliveryStatus.failed.value,
            )
        )
        or 0
    )

    background_jobs_30d = (
        db.scalar(select(func.count()).select_from(BackgroundJob).where(BackgroundJob.created_at >= since_30d)) or 0
    )
    background_jobs_succeeded_30d = (
        db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.created_at >= since_30d,
                BackgroundJob.status == JobStatus.succeeded.value,
            )
        )
        or 0
    )
    background_jobs_failed_30d = (
        db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.created_at >= since_30d,
                BackgroundJob.status == JobStatus.permanently_failed.value,
            )
        )
        or 0
    )

    emails_sent_30d = (
        db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.created_at >= since_30d,
                BackgroundJob.job_type == JobType.notification_email.value,
                BackgroundJob.status == JobStatus.succeeded.value,
            )
        )
        or 0
    )

    notifications_created_30d = (
        db.scalar(select(func.count()).select_from(Notification).where(Notification.created_at >= since_30d)) or 0
    )

    return UsageMetrics(
        ai_requests_30d=ai_requests_30d,
        api_keys_active=api_keys_active,
        api_keys_used_7d=api_keys_used_7d,
        webhook_deliveries_30d=webhook_deliveries_30d,
        webhook_deliveries_succeeded_30d=webhook_deliveries_succeeded_30d,
        webhook_deliveries_failed_30d=webhook_deliveries_failed_30d,
        background_jobs_30d=background_jobs_30d,
        background_jobs_succeeded_30d=background_jobs_succeeded_30d,
        background_jobs_failed_30d=background_jobs_failed_30d,
        emails_sent_30d=emails_sent_30d,
        notifications_created_30d=notifications_created_30d,
    )
