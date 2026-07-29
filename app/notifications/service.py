"""app.notifications.service.emit_event -- the one central call every
business service function makes to raise a domain event across every
channel this app supports: outbound webhooks (delegated, byte-for-byte
unchanged, to app.services.webhook_events.record_webhook_event), in-app
notifications, and notification emails. See docs/notifications.md for
the full architecture and app.webhook_event_type.WebhookEventType for the
closed catalog of event types this function accepts.

Like record_webhook_event, this function never commits and never
performs network I/O -- the caller's own existing db.commit() (already
present at the exact call site for the business mutation itself) is what
makes all three channels durable together, atomically, in one
transaction. If that commit never happens, none of the three channels'
rows ever existed either.

Deliberately NOT gated by app.billing.capabilities.can_use_background_jobs
(unlike the webhook channel, which record_webhook_event itself already
gates): in-app/email notifications are a baseline platform capability
every organization gets regardless of plan, not a premium feature --
only outbound webhook delivery infrastructure is plan-gated.

FROZEN as of Phase 20 approval: this is the single, standing entry point
for every domain event this platform raises -- see docs/notifications.md's
own "Governance" section. A future channel (Slack, Discord, SMS, Push,
audit, analytics, ...) is added as a new subscriber inside this function's
own fan-out (or a consumer of the WebhookEvent row it writes), never as a
second call site elsewhere that reacts to a business mutation directly.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.job_type import JobType
from app.membership_status import MembershipStatus
from app.models import Notification, NotificationPreference, OrganizationMember, User
from app.notifications.copy import render_notification_copy
from app.services.background_jobs import enqueue_job
from app.services.webhook_events import record_webhook_event
from app.webhook_event_type import WebhookEventType


def is_email_enabled(db: Session, *, user_id: str, organization_id: str) -> bool:
    """Default True -- see NotificationPreference's own docstring for why
    the absence of a row means the default, not False."""
    preference = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.organization_id == organization_id,
        )
    )
    return True if preference is None else preference.email_enabled


def set_email_enabled(
    db: Session, *, user_id: str, organization_id: str, enabled: bool
) -> NotificationPreference:
    """Creates the preference row lazily on its first change, or updates
    it in place thereafter -- matches ProviderCustomer's own
    get-or-create-on-demand precedent from the billing domain. The
    caller commits."""
    preference = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.organization_id == organization_id,
        )
    )
    if preference is None:
        preference = NotificationPreference(
            user_id=user_id, organization_id=organization_id, email_enabled=enabled
        )
        db.add(preference)
    else:
        preference.email_enabled = enabled
    db.flush()
    return preference


def emit_event(
    db: Session,
    *,
    organization_id: str,
    event_type: WebhookEventType,
    object_type: str,
    object_id: str,
    payload: dict,
) -> None:
    """Fans one domain event out to all three channels. Every active
    member of the organization gets exactly one Notification row
    (in-app, unconditional -- see Notification's own docstring), and one
    notification.email BackgroundJob for every active member who hasn't
    opted out via NotificationPreference AND has a verified email
    address (an unverified address never receives any transactional
    email in this app -- matches the invitation/reminder precedent)."""
    event, _deliveries = record_webhook_event(
        db,
        organization_id=organization_id,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        payload=payload,
    )

    members = db.scalars(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == MembershipStatus.active.value,
        )
    ).all()
    if not members:
        return

    title, body = render_notification_copy(event_type, payload)

    notifications: list[Notification] = []
    for member in members:
        notification = Notification(
            organization_id=organization_id,
            user_id=member.user_id,
            event_id=event.id,
            event_type=event_type.value,
            title=title,
            body=body,
            object_type=object_type,
            object_id=object_id,
        )
        db.add(notification)
        notifications.append(notification)
    db.flush()

    for notification in notifications:
        if not is_email_enabled(db, user_id=notification.user_id, organization_id=organization_id):
            continue
        user = db.get(User, notification.user_id)
        if user is None or not user.email_verified:
            continue
        enqueue_job(
            db,
            job_type=JobType.notification_email,
            payload={"notification_id": notification.id},
            organization_id=organization_id,
            idempotency_key=f"notification-email:{notification.id}",
        )
