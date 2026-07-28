"""The outbound HTTP delivery engine -- the only place in this app that
actually sends a webhook over the network. Two entry points:

  - deliver_webhook(db, delivery_id): performs exactly ONE attempt for an
    existing `pending` WebhookDelivery row, called by
    app.services.webhook_dispatch immediately after the transaction that
    created it commits (see that module's docstring for why dispatch is
    triggered from a Session commit hook rather than FastAPI
    BackgroundTasks).
  - resend_delivery(...): the manual-resend action. Creates a brand-new
    WebhookDelivery row (trigger=manual_resend, same event_id, a fresh
    attempt_number) and schedules it exactly like an automatic delivery --
    it NEVER mutates or re-sends the original row, matching
    WebhookDelivery's own "never re-used for a second attempt" docstring.

Delivery guarantee: at-least-once, never exactly-once. Every WebhookEvent
id is stable and immutable; consumers are expected to dedupe on it (see
the X-Webhook-Delivery / event payload's own `id` field). A process
restart mid-flight can lose one in-flight attempt, but the WebhookDelivery
row itself is already committed and remains visible/resendable -- nothing
is ever silently lost from the UI's perspective, only the one attempt
that happened to be in-flight.

Explicit scope boundary (Phase 15B): this module computes `next_retry_at`
on a failed delivery (a fixed backoff schedule) but NEVER reads it back to
actually perform a retry -- there is no scheduler, poller, or retry loop
anywhere in this codebase. A future Phase 15C worker owns that.

Uses `requests` (never httpx, which is test-infra only in this project),
matching app.email.resend_provider's exact conventions: an int/tuple
`timeout` kwarg, `response.raise_for_status()`, and a two-way except split
between requests.exceptions.HTTPError (reached, but a non-2xx status) and
requests.exceptions.RequestException (never reached the server at all).
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.models import User, WebhookDelivery, WebhookEndpoint, WebhookEvent
from app.services.webhook_audit import record_webhook_action
from app.services.webhook_dispatch import schedule_delivery
from app.webhook_audit_action import WebhookAuditAction
from app.webhook_delivery_status import WebhookDeliveryStatus
from app.webhook_delivery_trigger import WebhookDeliveryTrigger
from app.webhook_signing import build_signed_headers
from app.webhook_ssrf import UnsafeWebhookUrlError, assert_public_url, safe_connection_scope

logger = logging.getLogger(__name__)

# (connect, read) seconds -- generous enough for a slow but legitimate
# receiver, short enough that one bad endpoint can never tie up a worker
# thread for long. Matches the shape (an explicit numeric timeout, never
# "no timeout") of app.email.resend_provider's own `timeout=15`.
_TIMEOUT = (5.0, 10.0)

# Response bodies are read but capped -- a malicious or misbehaving
# receiver returning gigabytes of body must never exhaust worker memory.
_MAX_RESPONSE_BODY_BYTES = 4096

# Fixed backoff schedule for `next_retry_at` -- metadata only (see module
# docstring: nothing in this codebase acts on it yet).
_RETRY_BACKOFF_SCHEDULE = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
]


class DeliveryNotFoundError(Exception):
    """No WebhookDelivery matches the given id."""


class DeliveryNotFoundInOrgError(Exception):
    """No WebhookDelivery matches the given id within this organization --
    used by the management router's tenant-scoped lookup, distinct from
    DeliveryNotFoundError which app.services.webhook_dispatch's
    background path uses (no organization to scope by there)."""


def _compute_next_retry_at(attempt_number: int) -> datetime:
    index = min(attempt_number - 1, len(_RETRY_BACKOFF_SCHEDULE) - 1)
    return datetime.now(timezone.utc) + _RETRY_BACKOFF_SCHEDULE[index]


def get_delivery_in_org(db: Session, organization_id: str, delivery_id: str) -> WebhookDelivery:
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.organization_id != organization_id:
        raise DeliveryNotFoundInOrgError(delivery_id)
    return delivery


def deliver_webhook(db: Session, delivery_id: str) -> WebhookDelivery:
    """Performs exactly one HTTP delivery attempt for `delivery_id` and
    records the outcome. A no-op if this row was already attempted
    (`attempted_at` is set) -- defense in depth guaranteeing at most one
    real HTTP call per row, even if something ever submitted the same id
    twice."""
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None:
        raise DeliveryNotFoundError(delivery_id)
    if delivery.attempted_at is not None:
        return delivery

    endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
    event = db.get(WebhookEvent, delivery.event_id)
    if endpoint is None or event is None:
        # Unreachable in normal operation (both FKs are populated at
        # creation time and neither row is ever hard-deleted -- see
        # WebhookEndpoint.active's own docstring), but this runs on a
        # background worker thread with no request/response cycle to
        # propagate an exception to, so it fails the row closed instead
        # of raising.
        delivery.status = WebhookDeliveryStatus.failed.value
        delivery.error_message = "endpoint_or_event_missing"
        delivery.attempted_at = datetime.now(timezone.utc)
        delivery.next_retry_at = _compute_next_retry_at(delivery.attempt_number)
        db.commit()
        return delivery

    # The wire body is an envelope, not the raw resource snapshot alone --
    # a receiver needs the STABLE event id (never the delivery id, which
    # is different on every resend) to dedupe, plus the event type/object
    # reference, without having to parse anything out of headers. Mirrors
    # the Stripe/GitHub convention of {id, type, ..., data}.
    envelope = {
        "id": event.id,
        "type": event.event_type,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "created_at": event.created_at.isoformat(),
        "data": json.loads(event.payload),
    }
    body = json.dumps(envelope).encode("utf-8")
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "InvoicingApp-Webhooks/1.0",
        **build_signed_headers(
            secret=endpoint.secret,
            event_type=event.event_type,
            delivery_id=delivery.id,
            timestamp=timestamp,
            body=body,
        ),
    }
    # Never logs endpoint.secret or the computed signature value -- only
    # that a delivery is about to be attempted, mirroring
    # ResendEmailSender.send's own "never log the credential" convention.
    logger.info(
        "deliver_webhook: attempting delivery delivery_id=%s endpoint_id=%s event_type=%s",
        delivery.id,
        endpoint.id,
        event.event_type,
    )

    started = time.monotonic()
    try:
        # Re-validated immediately before every attempt, not just at
        # endpoint creation/update time -- see app.webhook_ssrf's module
        # docstring for why (a DNS record safe yesterday may not be safe
        # today). safe_connection_scope additionally re-validates at
        # actual TCP-connect time, closing the gap this pre-flight check
        # alone can't.
        assert_public_url(endpoint.url)
        with safe_connection_scope():
            response = requests.post(
                endpoint.url,
                data=body,
                headers=headers,
                timeout=_TIMEOUT,
                allow_redirects=False,
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        response_snippet = response.content[:_MAX_RESPONSE_BODY_BYTES].decode("utf-8", errors="replace")

        delivery.response_status_code = response.status_code
        delivery.response_body_snippet = response_snippet
        delivery.duration_ms = duration_ms
        delivery.request_headers = _headers_for_storage(headers)
        delivery.attempted_at = datetime.now(timezone.utc)

        if 200 <= response.status_code < 300:
            delivery.status = WebhookDeliveryStatus.succeeded.value
            logger.info(
                "deliver_webhook: delivery succeeded delivery_id=%s status_code=%s duration_ms=%s",
                delivery.id,
                response.status_code,
                duration_ms,
            )
        else:
            delivery.status = WebhookDeliveryStatus.failed.value
            delivery.next_retry_at = _compute_next_retry_at(delivery.attempt_number)
            logger.warning(
                "deliver_webhook: delivery failed (non-2xx) delivery_id=%s status_code=%s",
                delivery.id,
                response.status_code,
            )
    except UnsafeWebhookUrlError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        delivery.status = WebhookDeliveryStatus.failed.value
        delivery.error_message = "unsafe_target_url"
        delivery.duration_ms = duration_ms
        delivery.attempted_at = datetime.now(timezone.utc)
        delivery.next_retry_at = _compute_next_retry_at(delivery.attempt_number)
        logger.error(
            "deliver_webhook: refused unsafe target delivery_id=%s reason=%s", delivery.id, exc.reason
        )
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        delivery.status = WebhookDeliveryStatus.failed.value
        delivery.error_message = f"{type(exc).__name__}: {exc}"[:500]
        delivery.duration_ms = duration_ms
        delivery.attempted_at = datetime.now(timezone.utc)
        delivery.next_retry_at = _compute_next_retry_at(delivery.attempt_number)
        logger.warning(
            "deliver_webhook: delivery failed (network) delivery_id=%s exception_type=%s",
            delivery.id,
            type(exc).__name__,
        )

    db.commit()
    db.refresh(delivery)
    return delivery


def _headers_for_storage(headers: dict[str, str]) -> str:
    """JSON-encodes the request headers for the delivery-detail view --
    safe to store verbatim: it contains the computed signature (a
    per-request derived value, not the secret itself) and no other
    sensitive value, mirroring how a signature is safe to show a user
    while the secret it was derived from never is."""
    return json.dumps(headers)


def resend_delivery(
    db: Session, original: WebhookDelivery, actor: User, *, client_ip: str | None = None
) -> WebhookDelivery:
    """Manual resend -- creates a brand-new `pending` WebhookDelivery row
    for the SAME event_id/endpoint_id (never mutates `original`), then
    schedules it for immediate delivery exactly like an automatic one.
    `attempt_number` continues the sequence for this event+endpoint pair
    so the delivery-history view can show "attempt 2 of ..." style
    context."""
    new_delivery = WebhookDelivery(
        organization_id=original.organization_id,
        event_id=original.event_id,
        endpoint_id=original.endpoint_id,
        status=WebhookDeliveryStatus.pending.value,
        trigger=WebhookDeliveryTrigger.manual_resend.value,
        attempt_number=original.attempt_number + 1,
        request_url=original.request_url,
    )
    db.add(new_delivery)
    record_webhook_action(
        db,
        organization_id=original.organization_id,
        action=WebhookAuditAction.delivery_resent,
        endpoint_id=original.endpoint_id,
        actor=actor,
        client_ip=client_ip,
        details={"original_delivery_id": original.id, "event_id": original.event_id},
    )
    db.commit()
    db.refresh(new_delivery)
    schedule_delivery(new_delivery.id)
    return new_delivery
