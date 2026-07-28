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

Actual HTTP delivery happens later, asynchronously, via
app.services.webhook_deliveries -- see app.routers.webhooks for exactly
where that's scheduled (a FastAPI BackgroundTask registered by the router
AFTER this function's caller has already returned/committed), never
inline in this function.
"""

import json

from sqlalchemy.orm import Session

from app.models import WebhookDelivery, WebhookEvent
from app.services.webhook_dispatch import mark_for_dispatch
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
    deliveries."""
    event = WebhookEvent(
        organization_id=organization_id,
        event_type=event_type.value,
        object_type=object_type,
        object_id=object_id,
        payload=json.dumps(payload, default=str),
    )
    db.add(event)
    db.flush()

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
        # Flush now so every delivery.id below is real (never None) --
        # independent of whenever the caller's own commit eventually
        # happens -- and mark each one for dispatch (see
        # app.services.webhook_dispatch) so the after_commit hook can
        # submit them for actual HTTP delivery the instant this
        # transaction becomes durable, never before.
        db.flush()
        for delivery in deliveries:
            mark_for_dispatch(db, delivery.id)

    return event, deliveries
