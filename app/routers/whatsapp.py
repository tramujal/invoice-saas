"""Settings-facing REST surface for the experimental WhatsApp assistant
(Phase 23) -- everything a user manages from Settings -> WhatsApp. This
router never talks to the bridge's inbound webhook contract (see
app.routers.whatsapp_bridge for that) and never interprets a natural-
language command itself -- it only ever calls app.whatsapp.service.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member, require_permission, require_verified_email
from app.models import User
from app.permissions import Permission
from app.whatsapp import queries, service
from app.whatsapp.provider_base import WhatsAppBridgeUnavailableError, WhatsAppNotConfiguredError, WhatsAppProviderError
from app.whatsapp.provider_factory import get_whatsapp_provider
from app.whatsapp.schemas import (
    WhatsAppCommandHistoryItemResponse,
    WhatsAppCommandHistoryResponse,
    WhatsAppConnectionResponse,
    WhatsAppIdentityListResponse,
    WhatsAppIdentityResponse,
    WhatsAppLinkRequest,
    WhatsAppLinkResponse,
    WhatsAppQrResponse,
    WhatsAppQuotaResponse,
    WhatsAppStatusResponse,
)
from app.billing.enforcement import CapabilityDeniedError

router = APIRouter(prefix="/organizations/{organization_id}/whatsapp", tags=["whatsapp"])


def _service_error_to_http(exc: service.WhatsAppServiceError) -> HTTPException:
    status_by_code = {
        "invalid_phone_number": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "phone_already_linked": status.HTTP_409_CONFLICT,
        "identity_not_found": status.HTTP_404_NOT_FOUND,
    }
    return HTTPException(
        status_code=status_by_code.get(exc.code, status.HTTP_400_BAD_REQUEST),
        detail={"code": exc.code, "message": str(exc)},
    )


def _identity_response(identity, user_email: str) -> WhatsAppIdentityResponse:
    return WhatsAppIdentityResponse(
        id=identity.id,
        user_id=identity.user_id,
        user_email=user_email,
        normalized_phone_number=identity.normalized_phone_number,
        status=identity.status,
        verified_at=identity.verified_at.isoformat() if identity.verified_at else None,
        last_message_at=identity.last_message_at.isoformat() if identity.last_message_at else None,
        created_at=identity.created_at.isoformat(),
    )


@router.get("/status", response_model=WhatsAppStatusResponse)
def get_whatsapp_status(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatsAppStatusResponse:
    require_org_member(current_user, organization_id, db)
    snapshot = service.get_status_snapshot(db, organization_id)
    connection = snapshot["connection"]
    return WhatsAppStatusResponse(
        transport_enabled=snapshot["transport_enabled"],
        transport_configured=snapshot["transport_configured"],
        plan_allows_whatsapp=snapshot["plan_allows_whatsapp"],
        plan_allows_voice_messages=snapshot["plan_allows_voice_messages"],
        connection=WhatsAppConnectionResponse(
            state=connection.state.value,
            connected_phone_number=connection.connected_phone_number,
            last_heartbeat_at=connection.last_heartbeat_at,
        ),
        whatsapp_users_quota=WhatsAppQuotaResponse(
            used=snapshot["whatsapp_users_used"],
            limit=snapshot["whatsapp_users_limit"],
            unlimited=snapshot["whatsapp_users_limit"] is None,
        ),
        whatsapp_actions_quota=WhatsAppQuotaResponse(
            used=snapshot["whatsapp_actions_used"],
            limit=snapshot["whatsapp_actions_limit"],
            unlimited=snapshot["whatsapp_actions_limit"] is None,
        ),
    )


@router.get("/me", response_model=WhatsAppIdentityResponse | None)
def get_my_whatsapp_identity(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_org_member(current_user, organization_id, db)
    identity = queries.get_identity_for_user_in_org(db, organization_id, current_user.id)
    if identity is None:
        return None
    return _identity_response(identity, current_user.email)


@router.post("/link", response_model=WhatsAppLinkResponse)
def link_whatsapp_number(
    organization_id: str,
    body: WhatsAppLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatsAppLinkResponse:
    require_verified_email(current_user)
    try:
        result = service.initiate_link(db, organization_id, current_user, body.phone_number)
    except service.WhatsAppServiceError as exc:
        raise _service_error_to_http(exc)
    except CapabilityDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_error_detail())
    return WhatsAppLinkResponse(
        identity_id=result.identity_id,
        normalized_phone_number=result.normalized_phone_number,
        status=result.status,
        verification_code=result.verification_code,
        verification_expires_at=result.verification_expires_at.isoformat(),
    )


@router.post("/me/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_whatsapp_number(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    require_verified_email(current_user)
    try:
        service.revoke_own_identity(db, organization_id, current_user, _own_identity_id_or_404(db, organization_id, current_user))
    except service.WhatsAppServiceError as exc:
        raise _service_error_to_http(exc)


def _own_identity_id_or_404(db: Session, organization_id: str, current_user: User) -> str:
    identity = queries.get_identity_for_user_in_org(db, organization_id, current_user.id)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "identity_not_found", "message": "No WhatsApp number is linked to your account."},
        )
    return identity.id


@router.get("/identities", response_model=WhatsAppIdentityListResponse)
def list_whatsapp_identities(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatsAppIdentityListResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    rows = queries.list_identities_for_org(db, organization_id)
    return WhatsAppIdentityListResponse(items=[_identity_response(identity, email) for identity, email in rows])


@router.post("/identities/{identity_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def admin_revoke_whatsapp_identity(
    organization_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    try:
        service.admin_revoke_identity(db, organization_id, identity_id)
    except service.WhatsAppServiceError as exc:
        raise _service_error_to_http(exc)


@router.get("/history", response_model=WhatsAppCommandHistoryResponse)
def get_whatsapp_history(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatsAppCommandHistoryResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    items = queries.list_command_history(db, organization_id, limit=20)
    return WhatsAppCommandHistoryResponse(
        items=[
            WhatsAppCommandHistoryItemResponse(
                id=row.id,
                message_type=row.message_type,
                command_action=row.command_action,
                status=row.status,
                failure_code=row.failure_code,
                created_at=row.created_at.isoformat(),
            )
            for row in items
        ]
    )


def _bridge_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, WhatsAppNotConfiguredError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "whatsapp_not_configured", "message": "The WhatsApp bridge is disabled or unconfigured."},
        )
    if isinstance(exc, WhatsAppBridgeUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "whatsapp_bridge_unavailable", "message": "The WhatsApp bridge is currently unreachable."},
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": "whatsapp_provider_error", "message": "The WhatsApp bridge reported an error."},
    )


@router.post("/qr", response_model=WhatsAppQrResponse)
def request_whatsapp_qr(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatsAppQrResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    try:
        qr = service.request_qr_code(db, organization_id, current_user)
    except (WhatsAppNotConfiguredError, WhatsAppBridgeUnavailableError, WhatsAppProviderError) as exc:
        raise _bridge_error_to_http(exc)
    return WhatsAppQrResponse(qr_data_base64=qr.qr_data_base64, expires_at=qr.expires_at)


@router.post("/reconnect", status_code=status.HTTP_204_NO_CONTENT)
def reconnect_whatsapp(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    try:
        get_whatsapp_provider().reconnect()
    except (WhatsAppNotConfiguredError, WhatsAppBridgeUnavailableError, WhatsAppProviderError) as exc:
        raise _bridge_error_to_http(exc)


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_whatsapp(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    try:
        get_whatsapp_provider().disconnect()
    except (WhatsAppNotConfiguredError, WhatsAppBridgeUnavailableError, WhatsAppProviderError) as exc:
        raise _bridge_error_to_http(exc)


@router.post("/session/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_whatsapp_session(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Explicit, irreversible session deletion (Phase 23 section 20) --
    the next connection attempt always starts from a fresh QR scan."""
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    try:
        get_whatsapp_provider().delete_session()
    except (WhatsAppNotConfiguredError, WhatsAppBridgeUnavailableError, WhatsAppProviderError) as exc:
        raise _bridge_error_to_http(exc)
