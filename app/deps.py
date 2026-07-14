import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.membership_role import MembershipRole
from app.membership_status import MembershipStatus
from app.models import OrganizationMember, User
from app.permissions import Permission, check_permission
from app.security import decode_access_token

security = HTTPBearer(auto_error=False)


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
    return user


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
    if not check_permission(MembershipRole(membership.role), permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "permission_denied",
                "message": f"This action requires the '{permission.value}' permission.",
            },
        )
    return membership


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
