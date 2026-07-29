"""Transaction-safe webhook event emission -- the ONLY function any
business service function calls to raise a webhook event (see this
phase's authoritative event-emission map, reproduced in each call site's
own comment: app.services.customers, app.services.products,
app.services.quotes, app.services.invoices, app.imports.customers,
app.imports.products, app.routers.platform_admin).

record_webhook_event does exactly one thing: `db.add()` a WebhookEvent row
plus one pending WebhookDelivery row per currently-subscribed endpoint.
It never commits and never performs network I/O -- the caller's own
existing `db.commit()` (already present at that exact call site for the
business mutation itself) is what makes the event durable, and is what
gives this whole design its core guarantee: if that commit never happens,
neither does the event, with no separate outbox table or two-phase
protocol required, because the event row was never a separate transaction
to begin with.

Actual HTTP delivery happens later, durably, via the Phase 15C job queue
(see app.services.background_jobs.enqueue_job and app.jobs.worker) --
this function enqueues one webhook.deliver BackgroundJob per pending
delivery it creates, in the SAME transaction, so a worker can claim and
execute it only once this transaction is durable. Never inline in this
function, and never via any in-process dispatch mechanism.
"""

import json

from sqlalchemy.orm import Session

from app.billing.capabilities import can_use_background_jobs, get_organization_capabilities
from app.job_type import JobType
from app.models import WebhookDelivery, WebhookEvent
from app.services.background_jobs import enqueue_job
from app.services.webhook_endpoints import list_active_subscribed_endpoints
from app.webhook_delivery_status import WebhookDeliveryStatus
from app.webhook_delivery_trigger import WebhookDeliveryTrigger
from app.webhook_event_type import WebhookEventType


def record_webhook_event(
    db: Session,
    *,
    organization_id: str,
    event_type: WebhookEventType,
    object_type: str,
    object_id: str,
    payload: dict,
) -> tuple[WebhookEvent, list[WebhookDelivery]]:
    """Adds (never commits) one WebhookEvent + one pending WebhookDelivery
    per currently-subscribed, enabled, active endpoint. Returns both so
    the caller's router can, AFTER its own commit succeeds, hand the
    delivery ids to app.services.webhook_deliveries for actual sending.

    If no endpoint is subscribed, the WebhookEvent row is still recorded
    (it's genuine, immutable history -- a webhook being added later could
    otherwise never look back at what already happened), just with zero
    deliveries. Phase 17B: the same applies if the organization's plan
    doesn't include background job processing at all
    (app.billing.capabilities.can_use_background_jobs) -- this is the
    one and only place that capability is enforced for the WEBHOOK
    channel specifically (Phase 20's notification.email job is
    deliberately NOT gated by this same capability -- see
    app.notifications.service.emit_event's own docstring for why). This
    matters most on a downgrade: an organization that had webhook
    endpoints configured on a higher plan keeps those rows (they are
    never deleted), but stops receiving deliveries the moment its plan
    no longer includes background jobs, without needing a separate
    sweep to disable them."""
    event = WebhookEvent(
        organization_id=organization_id,
        event_type=event_type.value,
        object_type=object_type,
        object_id=object_id,
        payload=json.dumps(payload, default=str),
    )
    db.add(event)
    db.flush()

    caps = get_organization_capabilities(db, organization_id)
    if not can_use_background_jobs(caps):
        return event, []

    endpoints = list_active_subscribed_endpoints(db, organization_id, event_type)
    deliveries: list[WebhookDelivery] = []
    for endpoint in endpoints:
        delivery = WebhookDelivery(
            organization_id=organization_id,
            event_id=event.id,
            endpoint_id=endpoint.id,
            status=WebhookDeliveryStatus.pending.value,
            trigger=WebhookDeliveryTrigger.automatic.value,
            attempt_number=1,
            request_url=endpoint.url,
        )
        db.add(delivery)
        deliveries.append(delivery)

    if deliveries:
        # Flush now so every delivery.id below is real (never None), then
        # durably enqueue one webhook.deliver job per delivery in this
        # same transaction -- if the caller's own commit never happens,
        # neither the delivery rows nor these job rows ever exist.
        db.flush()
        for delivery in deliveries:
            enqueue_job(
                db,
                job_type=JobType.webhook_deliver,
                payload={"delivery_id": delivery.id},
                organization_id=organization_id,
                idempotency_key=f"webhook-delivery:{delivery.id}",
            )

    return event, deliveries
