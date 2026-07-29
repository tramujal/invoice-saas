"""Browser-facing outbound webhook management -- endpoint CRUD/enable/
disable/rotate-secret/archive, plus delivery history and manual resend.
Gated behind the same Permission.settings_manage RBAC every other
security-sensitive integration-settings endpoint uses (mirrors
app.routers.api_key_management exactly).
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.models import User, WebhookDelivery, WebhookEndpoint, WebhookEvent
from app.permissions import Permission
from app.rate_limit import (
    RateLimitCheck,
    WEBHOOK_ENDPOINT_WRITE_RULES,
    WEBHOOK_READ_RULES,
    WEBHOOK_RESEND_RULES,
    enforce_rate_limit,
    get_client_ip,
    user_identity,
)
from app.schemas import (
    PaginatedWebhookDeliveriesResponse,
    WebhookDeliveryDetailResponse,
    WebhookDeliveryResponse,
    WebhookEndpointCreateRequest,
    WebhookEndpointCreatedResponse,
    WebhookEndpointResponse,
    WebhookEndpointUpdateRequest,
    WebhookEventCatalogEntry,
    WebhookEventResponse,
)
from app.services.webhook_deliveries import (
    DeliveryNotFoundInOrgError,
    get_delivery_in_org,
    resend_delivery,
)
from app.services.webhook_endpoints import (
    WebhookEndpointNotFoundError,
    archive_endpoint,
    create_endpoint,
    decode_events,
    get_endpoint_in_org,
    list_endpoints_in_org,
    rotate_endpoint_secret,
    set_endpoint_enabled,
    update_endpoint,
    WILDCARD_EVENT,
)
from app.services.plan_limits import PlanLimitExceededError
from app.webhook_event_type import WebhookEventType, event_domain
from app.webhook_ssrf import UnsafeWebhookUrlError

router = APIRouter(prefix="/organizations/{organization_id}/webhooks", tags=["webhooks"])


def _rate_limit_write(request: Request, current_user: User) -> None:
    enforce_rate_limit(
        [RateLimitCheck(scope="webhooks:write", identity=user_identity(current_user.id), rules=WEBHOOK_ENDPOINT_WRITE_RULES)]
    )


def _rate_limit_read(request: Request, current_user: User) -> None:
    enforce_rate_limit(
        [RateLimitCheck(scope="webhooks:read", identity=user_identity(current_user.id), rules=WEBHOOK_READ_RULES)]
    )


def _parse_subscribed_events(raw: list[str]) -> frozenset[WebhookEventType] | None:
    """None means "wildcard" -- see app.services.webhook_endpoints
    ._encode_events. The request schema already validated every entry is
    either "*" or a real WebhookEventType value."""
    if WILDCARD_EVENT in raw:
        return None
    return frozenset(WebhookEventType(v) for v in raw)


def _to_endpoint_response(endpoint: WebhookEndpoint) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=endpoint.id,
        organization_id=endpoint.organization_id,
        url=endpoint.url,
        description=endpoint.description,
        subscribed_events=decode_events(endpoint.subscribed_events),
        enabled=endpoint.enabled,
        active=endpoint.active,
        created_by=endpoint.created_by,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
        last_rotated_at=endpoint.last_rotated_at,
    )


def _to_created_response(endpoint: WebhookEndpoint, secret: str) -> WebhookEndpointCreatedResponse:
    return WebhookEndpointCreatedResponse(**_to_endpoint_response(endpoint).model_dump(), secret=secret)


def _to_delivery_response(delivery: WebhookDelivery) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse(
        id=delivery.id,
        organization_id=delivery.organization_id,
        event_id=delivery.event_id,
        endpoint_id=delivery.endpoint_id,
        status=delivery.status,
        trigger=delivery.trigger,
        attempt_number=delivery.attempt_number,
        request_url=delivery.request_url,
        response_status_code=delivery.response_status_code,
        response_body_snippet=delivery.response_body_snippet,
        error_message=delivery.error_message,
        duration_ms=delivery.duration_ms,
        attempted_at=delivery.attempted_at,
        next_retry_at=delivery.next_retry_at,
        created_at=delivery.created_at,
    )


def _to_event_response(event: WebhookEvent) -> WebhookEventResponse:
    return WebhookEventResponse(
        id=event.id,
        organization_id=event.organization_id,
        event_type=event.event_type,
        object_type=event.object_type,
        object_id=event.object_id,
        payload=json.loads(event.payload),
        created_at=event.created_at,
    )


def _endpoint_or_404(db: Session, organization_id: str, endpoint_id: str) -> WebhookEndpoint:
    try:
        return get_endpoint_in_org(db, organization_id, endpoint_id)
    except WebhookEndpointNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook endpoint not found")


def _unsafe_url_error(exc: UnsafeWebhookUrlError) -> HTTPException:
    # Never surfaces exc.reason to the caller -- see UnsafeWebhookUrlError's
    # own docstring: no oracle for probing internal network layout. The
    # real reason is already logged server-side by the SSRF module itself
    # were it to log (it doesn't currently, but nothing here re-exposes it).
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "unsafe_webhook_url",
            "message": "This URL cannot be used as a webhook target.",
        },
    )


@router.get("/event-types", response_model=list[WebhookEventCatalogEntry])
def list_webhook_event_types(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WebhookEventCatalogEntry]:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    return [
        WebhookEventCatalogEntry(event_type=e.value, domain=event_domain(e)) for e in WebhookEventType
    ]


@router.post("", response_model=WebhookEndpointCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_webhook_endpoint(
    organization_id: str,
    body: WebhookEndpointCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookEndpointCreatedResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    _rate_limit_write(request, current_user)
    try:
        endpoint, secret = create_endpoint(
            db,
            organization_id,
            current_user,
            url=body.url,
            description=body.description,
            subscribed_events=_parse_subscribed_events(body.subscribed_events),
            client_ip=get_client_ip(request),
        )
    except UnsafeWebhookUrlError as exc:
        raise _unsafe_url_error(exc)
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())
    return _to_created_response(endpoint, secret)


@router.get("", response_model=list[WebhookEndpointResponse])
def list_webhook_endpoints(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WebhookEndpointResponse]:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    return [_to_endpoint_response(e) for e in list_endpoints_in_org(db, organization_id)]


@router.get("/{endpoint_id}", response_model=WebhookEndpointResponse)
def get_webhook_endpoint(
    organization_id: str,
    endpoint_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookEndpointResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    return _to_endpoint_response(_endpoint_or_404(db, organization_id, endpoint_id))


@router.patch("/{endpoint_id}", response_model=WebhookEndpointResponse)
def update_webhook_endpoint(
    organization_id: str,
    endpoint_id: str,
    body: WebhookEndpointUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookEndpointResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    _rate_limit_write(request, current_user)
    endpoint = _endpoint_or_404(db, organization_id, endpoint_id)
    fields_given = body.model_fields_set
    try:
        endpoint = update_endpoint(
            db,
            endpoint,
            current_user,
            url=body.url,
            description=body.description,
            subscribed_events=_parse_subscribed_events(body.subscribed_events)
            if body.subscribed_events is not None
            else None,
            subscribed_events_given="subscribed_events" in fields_given,
            client_ip=get_client_ip(request),
        )
    except UnsafeWebhookUrlError as exc:
        raise _unsafe_url_error(exc)
    return _to_endpoint_response(endpoint)


@router.post("/{endpoint_id}/enable", response_model=WebhookEndpointResponse)
def enable_webhook_endpoint(
    organization_id: str,
    endpoint_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookEndpointResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    endpoint = _endpoint_or_404(db, organization_id, endpoint_id)
    endpoint = set_endpoint_enabled(db, endpoint, current_user, enabled=True, client_ip=get_client_ip(request))
    return _to_endpoint_response(endpoint)


@router.post("/{endpoint_id}/disable", response_model=WebhookEndpointResponse)
def disable_webhook_endpoint(
    organization_id: str,
    endpoint_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookEndpointResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    endpoint = _endpoint_or_404(db, organization_id, endpoint_id)
    endpoint = set_endpoint_enabled(db, endpoint, current_user, enabled=False, client_ip=get_client_ip(request))
    return _to_endpoint_response(endpoint)


@router.post("/{endpoint_id}/rotate-secret", response_model=WebhookEndpointCreatedResponse)
def rotate_webhook_endpoint_secret(
    organization_id: str,
    endpoint_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookEndpointCreatedResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    _rate_limit_write(request, current_user)
    endpoint = _endpoint_or_404(db, organization_id, endpoint_id)
    endpoint, secret = rotate_endpoint_secret(db, endpoint, current_user, client_ip=get_client_ip(request))
    return _to_created_response(endpoint, secret)


@router.delete("/{endpoint_id}", response_model=WebhookEndpointResponse)
def archive_webhook_endpoint(
    organization_id: str,
    endpoint_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookEndpointResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    endpoint = _endpoint_or_404(db, organization_id, endpoint_id)
    endpoint = archive_endpoint(db, endpoint, current_user, client_ip=get_client_ip(request))
    return _to_endpoint_response(endpoint)


@router.get("/{endpoint_id}/deliveries", response_model=PaginatedWebhookDeliveriesResponse)
def list_webhook_deliveries(
    organization_id: str,
    endpoint_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedWebhookDeliveriesResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    _rate_limit_read(request, current_user)
    _endpoint_or_404(db, organization_id, endpoint_id)  # 404s before leaking any delivery rows

    base_query = select(WebhookDelivery).where(
        WebhookDelivery.organization_id == organization_id,
        WebhookDelivery.endpoint_id == endpoint_id,
    )
    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    rows = db.scalars(
        base_query.order_by(WebhookDelivery.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return PaginatedWebhookDeliveriesResponse(total=total, items=[_to_delivery_response(d) for d in rows])


@router.get("/deliveries/{delivery_id}", response_model=WebhookDeliveryDetailResponse)
def get_webhook_delivery(
    organization_id: str,
    delivery_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookDeliveryDetailResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    _rate_limit_read(request, current_user)
    try:
        delivery = get_delivery_in_org(db, organization_id, delivery_id)
    except DeliveryNotFoundInOrgError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook delivery not found")
    event = db.get(WebhookEvent, delivery.event_id)
    base = _to_delivery_response(delivery).model_dump()
    return WebhookDeliveryDetailResponse(
        **base,
        request_headers=json.loads(delivery.request_headers) if delivery.request_headers else None,
        event=_to_event_response(event),
    )


@router.post("/deliveries/{delivery_id}/resend", response_model=WebhookDeliveryResponse)
def resend_webhook_delivery(
    organization_id: str,
    delivery_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookDeliveryResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    enforce_rate_limit(
        [RateLimitCheck(scope="webhooks:resend", identity=user_identity(current_user.id), rules=WEBHOOK_RESEND_RULES)]
    )
    try:
        original = get_delivery_in_org(db, organization_id, delivery_id)
    except DeliveryNotFoundInOrgError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook delivery not found")
    new_delivery = resend_delivery(db, original, current_user, client_ip=get_client_ip(request))
    return _to_delivery_response(new_delivery)
