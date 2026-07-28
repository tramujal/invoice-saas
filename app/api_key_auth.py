"""Public API (/api/v1) authentication -- Organization API Keys.

Deliberately NOT a variant of app.deps.get_current_user: a key
authenticates as "this organization, with these granted scopes," never
as a specific human user, so reusing the User-shaped dependency would
force a fake/synthetic User onto every downstream call for no benefit --
every service function this API reuses (create_customer_record,
check_limit, get_organization_entitlements, ...) already takes
organization_id directly, never a User. This is a parallel, independent
authentication path with its own dependency, its own error shapes, and
its own context type, per this phase's explicit instruction not to
reuse browser session authentication.

Authorization header format: "Bearer sk_<prefix>_<secret>" -- the same
Bearer scheme browser sessions use (so existing HTTP client tooling
needs no special casing), but the token itself is this app's own
API-key format (see app.api_keys), never a JWT.

Failure responses are deliberately generic and uniform (single
"invalid_api_key" 401) regardless of *why* authentication failed --
missing header, malformed key, unknown prefix, wrong secret, revoked,
or expired all produce byte-identical responses. This is anti-
enumeration by construction: a caller probing prefixes can never learn
from the response alone whether a given prefix is registered at all,
only ever "not accepted." Internally, `record_api_key_action` still logs
the real reason for anything attributable to a known organization (see
below), so operators lose none of that detail -- only external callers
do.
"""

import json
import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api_key_audit_action import ApiKeyAuditAction
from app.api_key_permissions import ApiKeyPermission, has_api_key_permission, parse_api_key_permissions
from app.api_key_status import ApiKeyStatus, get_effective_api_key_status
from app.api_keys import InvalidApiKeyFormatError, parse_api_key, verify_api_key_secret
from app.database import get_db
from app.deps import _ensure_not_in_maintenance_mode, _ensure_organization_active
from app.rate_limit import (
    API_KEY_AUTH_IP_RULES,
    API_KEY_REQUEST_RULES,
    RateLimitCheck,
    api_key_identity,
    enforce_rate_limit,
    get_client_ip,
    ip_identity,
)
from app.services.organization_api_key_audit import record_api_key_action
from app.services.organization_api_keys import find_api_key_by_prefix, touch_api_key_last_used

logger = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)

_INVALID_KEY_DETAIL = {"code": "invalid_api_key", "message": "Invalid or missing API key."}


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_INVALID_KEY_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass(frozen=True)
class ApiKeyContext:
    """The authenticated principal for every /api/v1 route -- deliberately
    holds only organization_id + granted permissions, never a User (see
    this module's own docstring)."""

    organization_id: str
    api_key_id: str
    api_key_name: str
    permissions: frozenset[ApiKeyPermission]


def get_api_key_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    db: Session = Depends(get_db),
) -> ApiKeyContext:
    enforce_rate_limit(
        [RateLimitCheck(scope="api:v1:auth", identity=ip_identity(request), rules=API_KEY_AUTH_IP_RULES)]
    )
    client_ip = get_client_ip(request)

    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized()

    try:
        prefix, secret = parse_api_key(credentials.credentials)
    except InvalidApiKeyFormatError:
        raise _unauthorized()

    api_key = find_api_key_by_prefix(db, prefix)
    if api_key is None:
        # No organization to attribute this to -- an unrecognized prefix
        # is server-level noise (or a probing attempt), not a tenant
        # event, so it's logged, never written to the per-org audit
        # table (which requires a real organization_id).
        logger.warning("api_key_auth: unknown key prefix presented, ip=%s", client_ip)
        raise _unauthorized()

    if not verify_api_key_secret(secret, api_key.hashed_secret):
        record_api_key_action(
            db,
            organization_id=api_key.organization_id,
            action=ApiKeyAuditAction.auth_failed,
            api_key_id=api_key.id,
            client_ip=client_ip,
        )
        db.commit()
        raise _unauthorized()

    effective_status = get_effective_api_key_status(api_key)
    if effective_status == ApiKeyStatus.revoked:
        record_api_key_action(
            db,
            organization_id=api_key.organization_id,
            action=ApiKeyAuditAction.revoked_key_used,
            api_key_id=api_key.id,
            client_ip=client_ip,
        )
        db.commit()
        raise _unauthorized()
    if effective_status == ApiKeyStatus.expired:
        record_api_key_action(
            db,
            organization_id=api_key.organization_id,
            action=ApiKeyAuditAction.expired_key_used,
            api_key_id=api_key.id,
            client_ip=client_ip,
        )
        db.commit()
        raise _unauthorized()

    # Same organization-level guards the browser path enforces (see
    # app.deps.require_permission) -- a suspended organization or an
    # app-wide maintenance window blocks the public API exactly like it
    # blocks the browser UI, never a separate/weaker check.
    _ensure_organization_active(api_key.organization_id, db)
    _ensure_not_in_maintenance_mode(db)

    # Per-key throttle, checked only now that the key is known-valid --
    # scoped by api_key_id, not IP, so it protects against one
    # compromised-but-still-valid key being hammered without penalizing
    # other legitimate keys that happen to share an egress IP.
    enforce_rate_limit(
        [RateLimitCheck(scope="api:v1:key", identity=api_key_identity(api_key.id), rules=API_KEY_REQUEST_RULES)]
    )

    touch_api_key_last_used(db, api_key, client_ip)

    return ApiKeyContext(
        organization_id=api_key.organization_id,
        api_key_id=api_key.id,
        api_key_name=api_key.name,
        permissions=parse_api_key_permissions(json.loads(api_key.permissions)),
    )


def require_api_key_permission(permission: ApiKeyPermission):
    """Dependency factory -- each route asks for exactly the one
    permission it needs, e.g. Depends(require_api_key_permission(
    ApiKeyPermission.customers_write)). A pure `in`-check against the
    key's own granted set (see app.api_key_permissions), never a giant
    if/elif chain, so a new permission never requires touching this
    function."""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        context: ApiKeyContext = Depends(get_api_key_context),
    ) -> ApiKeyContext:
        if not has_api_key_permission(context.permissions, permission):
            record_api_key_action(
                db,
                organization_id=context.organization_id,
                action=ApiKeyAuditAction.permission_denied,
                api_key_id=context.api_key_id,
                client_ip=get_client_ip(request),
                details={"required_permission": permission.value},
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "api_key_permission_denied",
                    "message": f"This API key does not have the '{permission.value}' permission.",
                },
            )
        return context

    return dependency
