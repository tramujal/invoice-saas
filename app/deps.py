import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.membership_role import MembershipRole
from app.membership_status import MembershipStatus
from app.models import Organization, OrganizationMember, User
from app.organization_status import OrganizationStatus
from app.permissions import Permission, check_permission
from app.platform_permissions import PlatformPermission, PlatformRole, check_platform_permission
from app.security import decode_access_token
from app.services.platform_settings import get_effective_settings
from app.user_status import UserStatus

security = HTTPBearer(auto_error=False)

ACCOUNT_DISABLED_MESSAGE = "This account has been disabled."


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Resolves the authenticated user from a JWT Bearer access token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if user.status == UserStatus.disabled.value:
        # Re-checked fresh from the DB on every single request (no
        # caching anywhere in this function) -- this is what makes a
        # disable take effect against a previously-issued JWT immediately,
        # with no JWT-payload change, revocation list, or session store
        # needed. Same mechanism app.deps._ensure_organization_active
        # already relies on for organization suspension.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "account_disabled", "message": ACCOUNT_DISABLED_MESSAGE},
        )
    return user


ORGANIZATION_SUSPENDED_MESSAGE = "This organization has been suspended."


def _ensure_organization_active(organization_id: str, db: Session) -> None:
    """The shared suspension boundary -- called from require_org_member and
    require_permission only *after* their own membership check has already
    passed. Deliberately in that order: a non-member probing a suspended
    org's endpoints must see the ordinary "not a member" 403 exactly as
    before, never learning the org's suspension state; only an actual
    member is told *why* they're locked out. A previously-issued JWT
    carries no cached notion of org status, so this always re-checks the
    live Organization row -- there is no way to bypass it by holding an
    older token.

    Platform-admin routes (require_platform_permission) never call this --
    they involve no organization_id at all, by construction, so an
    organization being suspended never blocks the platform admin who needs
    to inspect or reactivate it.
    """
    org_status = db.scalar(select(Organization.status).where(Organization.id == organization_id))
    if org_status == OrganizationStatus.suspended.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "organization_suspended", "message": ORGANIZATION_SUSPENDED_MESSAGE},
        )


MAINTENANCE_MODE_MESSAGE = "The platform is currently undergoing maintenance. Please try again shortly."


def _ensure_not_in_maintenance_mode(db: Session) -> None:
    """The global sibling of _ensure_organization_active -- blocks every
    org-scoped route (via require_org_member/require_permission) the same
    way, but for a platform-wide condition rather than a per-org one.
    Reads app.services.platform_settings.get_effective_settings fresh on
    every call (no caching anywhere in that module), which is what makes
    a previously-issued JWT unable to bypass a maintenance window that
    started after the token was issued -- there is no cached notion of
    "maintenance" anywhere in the token or in this process.

    Platform-admin routes (require_platform_permission) never call this
    -- by construction they involve no organization_id at all, so a
    SUPER_ADMIN can always reach /admin/* to turn maintenance mode back
    off, exactly as required."""
    settings = get_effective_settings(db)
    if settings.maintenance_mode:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "maintenance_mode", "message": MAINTENANCE_MODE_MESSAGE},
        )


def require_org_member(user: User, organization_id: str, db: Session) -> None:
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == organization_id,
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this organization",
        )
    _ensure_organization_active(organization_id, db)
    _ensure_not_in_maintenance_mode(db)


def require_permission(
    user: User, organization_id: str, permission: Permission, db: Session
) -> OrganizationMember:
    """Supersedes a bare require_org_member call wherever a specific
    capability (not just membership) is needed. Internally re-does
    require_org_member's exact membership query, additionally filtered to
    status == active -- so this never weakens today's check, it
    strengthens it (a soft-removed member, which couldn't exist before
    this feature, now correctly fails here too). Returns the caller's own
    membership row so call sites that also need the role (e.g. the team
    management endpoints) get it for free, with no second query.

    Two things this single check can't express -- granting/revoking the
    "owner" role, and the "at least one other active owner must remain"
    invariant -- are data-dependent and live in app.services.team instead.
    """
    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == MembershipStatus.active.value,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this organization",
        )
    _ensure_organization_active(organization_id, db)
    _ensure_not_in_maintenance_mode(db)
    try:
        role = MembershipRole(membership.role)
    except ValueError:
        # A hand-edited or corrupted role value -- fails closed exactly
        # like require_platform_permission's handling of an unrecognized
        # platform_role, never lets the ValueError escape as an
        # unhandled 500.
        role = None
    if role is None or not check_permission(role, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "message": f"This action requires the '{permission.value}' permission.",
            },
        )
    return membership


def require_platform_permission(user: User, permission: PlatformPermission) -> None:
    """Gates platform-administration routes -- a completely separate
    authorization axis from require_permission/OrganizationMember. No
    organization_id is involved: platform permissions are never scoped to
    a tenant, by construction (see app.platform_permissions). A user with
    no platform_role is rejected the same way as one whose role lacks the
    specific permission, so callers can't distinguish "not an admin at
    all" from "admin, but not authorized for this" -- there's nothing
    useful either way for a caller to do differently.

    A platform_role value that isn't a recognized PlatformRole (hand-edited
    data, or a role retired in a future migration) is treated as "no
    platform role" and denied -- fails closed with a clean 403, never lets
    PlatformRole(...)'s ValueError escape as an unhandled 500."""
    role: PlatformRole | None = None
    if user.platform_role is not None:
        try:
            role = PlatformRole(user.platform_role)
        except ValueError:
            role = None

    if role is None or not check_platform_permission(role, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "platform_permission_denied",
                "message": f"This action requires the '{permission.value}' platform permission.",
            },
        )


EMAIL_NOT_VERIFIED_MESSAGE = (
    "Please verify your email address before performing this action."
)


def require_verified_email(user: User) -> None:
    """Gates business-data writes (creating/updating/deleting customers,
    creating invoices, sending invoice emails, updating organization
    settings) behind a verified email. Read-only endpoints, the dashboard,
    and invoice payment-status updates are deliberately left ungated — see
    the call sites in customers.py/invoices.py/organizations.py.

    `detail` is a structured object (not a plain string, unlike
    require_org_member's 403) specifically so the frontend can recognize
    this exact failure mode via `detail.code` and show a targeted "verify
    your email" message instead of a generic error.
    """
    if user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "email_not_verified", "message": EMAIL_NOT_VERIFIED_MESSAGE},
        )
