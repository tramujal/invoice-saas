"""Browser-facing API key management -- create/list/rotate/revoke, gated
behind the same browser-session RBAC every other organization-settings
endpoint uses (Permission.settings_manage: owner+admin only, matching
"who can change security-sensitive integration settings"). This is
deliberately NOT part of the public /api/v1 surface -- a caller must
already be an authenticated organization member to create the first key
in the first place (a key can't create itself).
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api_key_permissions import ApiKeyPermission, parse_api_key_permissions
from app.api_key_status import get_effective_api_key_status
from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.models import OrganizationApiKey, User
from app.permissions import Permission
from app.rate_limit import get_client_ip
from app.schemas import ApiKeyCreatedResponse, ApiKeyCreateRequest, ApiKeyResponse
from app.services.organization_api_keys import (
    ApiKeyNotFoundError,
    create_api_key,
    get_api_key_in_org,
    list_api_keys_in_org,
    revoke_api_key,
    rotate_api_key,
)
from app.services.plan_limits import PlanLimitExceededError

router = APIRouter(
    prefix="/organizations/{organization_id}/api-keys", tags=["api-key-management"]
)


def _to_response(api_key: OrganizationApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        organization_id=api_key.organization_id,
        name=api_key.name,
        description=api_key.description,
        prefix=api_key.prefix,
        permissions=sorted(parse_api_key_permissions(json.loads(api_key.permissions)), key=lambda p: p.value),
        status=get_effective_api_key_status(api_key),
        created_by=api_key.created_by,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        last_used_ip=api_key.last_used_ip,
        revoked_at=api_key.revoked_at,
        revoked_by=api_key.revoked_by,
    )


def _to_created_response(api_key: OrganizationApiKey, full_key: str) -> ApiKeyCreatedResponse:
    return ApiKeyCreatedResponse(**_to_response(api_key).model_dump(), api_key=full_key)


def _api_key_or_404(db: Session, organization_id: str, api_key_id: str) -> OrganizationApiKey:
    try:
        return get_api_key_in_org(db, organization_id, api_key_id)
    except ApiKeyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_organization_api_key(
    organization_id: str,
    body: ApiKeyCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiKeyCreatedResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    try:
        api_key, full_key = create_api_key(
            db,
            organization_id,
            current_user,
            name=body.name,
            description=body.description,
            permissions=frozenset(body.permissions),
            expires_at=body.expires_at,
            client_ip=get_client_ip(request),
        )
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())
    return _to_created_response(api_key, full_key)


@router.get("", response_model=list[ApiKeyResponse])
def list_organization_api_keys(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApiKeyResponse]:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    return [_to_response(k) for k in list_api_keys_in_org(db, organization_id)]


@router.post("/{api_key_id}/rotate", response_model=ApiKeyCreatedResponse)
def rotate_organization_api_key(
    organization_id: str,
    api_key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiKeyCreatedResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    api_key = _api_key_or_404(db, organization_id, api_key_id)
    new_key, full_key = rotate_api_key(db, api_key, current_user, client_ip=get_client_ip(request))
    return _to_created_response(new_key, full_key)


@router.post("/{api_key_id}/revoke", response_model=ApiKeyResponse)
def revoke_organization_api_key(
    organization_id: str,
    api_key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiKeyResponse:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    api_key = _api_key_or_404(db, organization_id, api_key_id)
    revoked = revoke_api_key(db, api_key, current_user, client_ip=get_client_ip(request))
    return _to_response(revoked)
