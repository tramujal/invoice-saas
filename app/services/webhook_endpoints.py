"""Organization webhook endpoint lifecycle: create, list, lookup, update,
enable/disable, rotate-secret, archive. The one place that
constructs/mutates WebhookEndpoint rows -- app.routers.webhooks calls into
this module rather than touching the model directly, mirroring
app.services.organization_api_keys's exact role for API keys.

Audit-writing is embedded directly in every mutating function here (same
deliberate deviation from app.services.platform_audit's router-calls-it
convention that app.services.organization_api_keys already established --
see that module's own docstring for the rationale: no per-call context is
ever needed beyond what's already available here, so embedding it is
strictly safer, impossible to forget).
"""

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, WebhookEndpoint
from app.webhook_audit_action import WebhookAuditAction
from app.webhook_event_type import WebhookEventType
from app.webhook_signing import generate_webhook_secret
from app.webhook_ssrf import assert_public_url
from app.services.plan_limits import LimitedResource, check_limit
from app.services.webhook_audit import record_webhook_action

WILDCARD_EVENT = "*"


class WebhookEndpointNotFoundError(Exception):
    """No webhook endpoint matches the given id within this organization."""


def _encode_events(event_types: frozenset[WebhookEventType] | None) -> str:
    """None (or an empty set) means "subscribed to everything" -- the
    wildcard is stored explicitly (["*"]) rather than as an empty list, so
    an empty list can never be misread as "subscribed to nothing" vs.
    "subscribed to everything" -- there is exactly one unambiguous
    representation for each."""
    if not event_types:
        return json.dumps([WILDCARD_EVENT])
    return json.dumps(sorted(e.value for e in event_types))


def decode_events(raw: str) -> list[str]:
    return json.loads(raw)


def is_subscribed(raw_subscribed_events: str, event_type: WebhookEventType) -> bool:
    values = decode_events(raw_subscribed_events)
    return WILDCARD_EVENT in values or event_type.value in values


def create_endpoint(
    db: Session,
    organization_id: str,
    actor: User,
    *,
    url: str,
    description: str,
    subscribed_events: frozenset[WebhookEventType] | None,
    client_ip: str | None = None,
) -> tuple[WebhookEndpoint, str]:
    """Returns (row, full_secret) -- full_secret is the only time the
    complete signing secret ever exists outside this function's local
    scope; the caller (the management router) must return it in the
    response body and never persist or log it, mirroring
    app.services.organization_api_keys.create_api_key exactly."""
    check_limit(db, organization_id, LimitedResource.webhooks)
    assert_public_url(url)
    full_secret = generate_webhook_secret()
    endpoint = WebhookEndpoint(
        organization_id=organization_id,
        url=url,
        description=description,
        subscribed_events=_encode_events(subscribed_events),
        secret=full_secret,
        created_by=actor.id,
    )
    db.add(endpoint)
    db.flush()
    record_webhook_action(
        db,
        organization_id=organization_id,
        action=WebhookAuditAction.endpoint_created,
        endpoint_id=endpoint.id,
        actor=actor,
        client_ip=client_ip,
        details={"url": url, "subscribed_events": decode_events(endpoint.subscribed_events)},
    )
    db.commit()
    db.refresh(endpoint)
    return endpoint, full_secret


def list_endpoints_in_org(db: Session, organization_id: str, *, include_archived: bool = False) -> list[WebhookEndpoint]:
    stmt = select(WebhookEndpoint).where(WebhookEndpoint.organization_id == organization_id)
    if not include_archived:
        stmt = stmt.where(WebhookEndpoint.active.is_(True))
    return list(db.scalars(stmt.order_by(WebhookEndpoint.created_at.desc())).all())


def list_active_subscribed_endpoints(
    db: Session, organization_id: str, event_type: WebhookEventType
) -> list[WebhookEndpoint]:
    """Used only by app.services.webhook_events.record_webhook_event --
    active + enabled endpoints whose subscription matches this event
    type. Filtered in Python (not SQL) since subscribed_events is a JSON
    TEXT column with no portable SQL-level JSON containment check that
    works identically on SQLite and Postgres -- the row count per
    organization is small enough (a handful of configured integrations,
    never thousands) that this is not a real performance concern."""
    endpoints = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.organization_id == organization_id,
            WebhookEndpoint.active.is_(True),
            WebhookEndpoint.enabled.is_(True),
        )
    ).all()
    return [e for e in endpoints if is_subscribed(e.subscribed_events, event_type)]


def get_endpoint_in_org(db: Session, organization_id: str, endpoint_id: str) -> WebhookEndpoint:
    endpoint = db.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.organization_id == organization_id,
        )
    )
    if endpoint is None:
        raise WebhookEndpointNotFoundError(endpoint_id)
    return endpoint


def update_endpoint(
    db: Session,
    endpoint: WebhookEndpoint,
    actor: User,
    *,
    url: str | None = None,
    description: str | None = None,
    subscribed_events: frozenset[WebhookEventType] | None = None,
    subscribed_events_given: bool = False,
    client_ip: str | None = None,
) -> WebhookEndpoint:
    """Partial update -- only fields explicitly given are changed.
    `subscribed_events_given` disambiguates "the caller passed an empty
    set, meaning wildcard" from "the caller didn't touch this field at
    all", the same _UNSET-sentinel problem app.services.quotes.update_quote_record
    solves for customer/expiry_date."""
    changes: dict = {}
    if url is not None and url != endpoint.url:
        assert_public_url(url)
        endpoint.url = url
        changes["url"] = url
    if description is not None:
        endpoint.description = description
    if subscribed_events_given:
        endpoint.subscribed_events = _encode_events(subscribed_events)
        changes["subscribed_events"] = decode_events(endpoint.subscribed_events)

    if changes:
        record_webhook_action(
            db,
            organization_id=endpoint.organization_id,
            action=WebhookAuditAction.endpoint_updated,
            endpoint_id=endpoint.id,
            actor=actor,
            client_ip=client_ip,
            details=changes,
        )
    db.commit()
    db.refresh(endpoint)
    return endpoint


def set_endpoint_enabled(
    db: Session, endpoint: WebhookEndpoint, actor: User, *, enabled: bool, client_ip: str | None = None
) -> WebhookEndpoint:
    """Idempotent -- matches Product.active's archive/restore precedent:
    re-applying the same state is a harmless no-op, not an error."""
    if endpoint.enabled != enabled:
        endpoint.enabled = enabled
        record_webhook_action(
            db,
            organization_id=endpoint.organization_id,
            action=WebhookAuditAction.endpoint_enabled if enabled else WebhookAuditAction.endpoint_disabled,
            endpoint_id=endpoint.id,
            actor=actor,
            client_ip=client_ip,
        )
        db.commit()
        db.refresh(endpoint)
    return endpoint


def rotate_endpoint_secret(
    db: Session, endpoint: WebhookEndpoint, actor: User, *, client_ip: str | None = None
) -> tuple[WebhookEndpoint, str]:
    """Overwrites `secret` in place -- see WebhookEndpoint's own docstring
    for why this differs from OrganizationApiKey's revoke-and-recreate
    rotation (single-active-secret is this phase's explicit design
    decision: there is no overlap window). Returns (endpoint,
    full_secret)."""
    full_secret = generate_webhook_secret()
    endpoint.secret = full_secret
    endpoint.last_rotated_at = datetime.now(timezone.utc)
    record_webhook_action(
        db,
        organization_id=endpoint.organization_id,
        action=WebhookAuditAction.endpoint_secret_rotated,
        endpoint_id=endpoint.id,
        actor=actor,
        client_ip=client_ip,
    )
    db.commit()
    db.refresh(endpoint)
    return endpoint, full_secret


def archive_endpoint(
    db: Session, endpoint: WebhookEndpoint, actor: User, *, client_ip: str | None = None
) -> WebhookEndpoint:
    """Idempotent soft-removal -- never a hard delete (see WebhookEndpoint's
    own docstring: WebhookDelivery rows must keep a meaningful
    endpoint_id)."""
    if endpoint.active:
        endpoint.active = False
        endpoint.enabled = False
        record_webhook_action(
            db,
            organization_id=endpoint.organization_id,
            action=WebhookAuditAction.endpoint_archived,
            endpoint_id=endpoint.id,
            actor=actor,
            client_ip=client_ip,
        )
        db.commit()
        db.refresh(endpoint)
    return endpoint
