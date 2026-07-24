"""Anonymous/authenticated-but-not-org-scoped public invitation endpoints
-- view and accept. Mirrors app/routers/quote_public.py's shape: no
organization_id anywhere in the URL, the token alone resolves the
invitation. Unlike the quote public flow, accept here DOES require an
authenticated caller (get_current_user) -- the entire point is creating a
real OrganizationMember tied to a real user_id, so "public" only means
"doesn't require prior membership in the org being joined."

Suspended organizations (see app.organization_status): view stays
available (an invitee should at least see why the invite currently can't
be actioned, rather than a raw error). accept is blocked -- there's no
reason to let someone join a currently-frozen organization; they'd just
find every org-scoped page locked out immediately afterward anyway.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.email.base import EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.email.invitation_templates import build_invitation_accepted_email
from app.models import User
from app.organization_status import OrganizationStatus
from app.rate_limit import (
    INVITATION_PUBLIC_ACCEPT_RULES,
    INVITATION_PUBLIC_VIEW_RULES,
    RateLimitCheck,
    enforce_rate_limit,
    ip_identity,
    user_identity,
)
from app.schemas import PublicInvitationAcceptResponse, PublicInvitationResponse
from app.services.plan_limits import PlanLimitExceededError
from app.services.platform_settings import get_effective_settings
from app.services.team import (
    InvalidInvitationRoleError,
    InvitationAlreadyAcceptedError,
    InvitationEmailMismatchError,
    InvitationExpiredError,
    InvitationNotFoundError,
    accept_invitation_record,
    get_invitation_by_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invitations/public", tags=["invitation_public"])


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True)
    # columns (Postgres returns aware ones) -- normalize before comparing,
    # same convention as app/routers/assistant_actions.py's _aware.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _invitation_by_token(db: Session, token: str):
    try:
        return get_invitation_by_token(db, token)
    except InvitationNotFoundError:
        # Never distinguishes "wrong token" from "not found" -- both are
        # exactly the same 404 to an anonymous caller.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")


@router.get("/{token}", response_model=PublicInvitationResponse)
def view_public_invitation(token: str, request: Request, db: Session = Depends(get_db)) -> PublicInvitationResponse:
    enforce_rate_limit(
        [RateLimitCheck(scope="invitations:public:view", identity=ip_identity(request), rules=INVITATION_PUBLIC_VIEW_RULES)]
    )
    invitation = _invitation_by_token(db, token)
    now = datetime.now(timezone.utc)
    organization = invitation.organization
    return PublicInvitationResponse(
        organization_name=organization.business_name or organization.name,
        inviter_email=invitation.created_by_email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        already_accepted=invitation.accepted_at is not None,
        expired=invitation.accepted_at is None and _aware(invitation.expires_at) < now,
    )


@router.post("/{token}/accept", response_model=PublicInvitationAcceptResponse)
def accept_public_invitation(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublicInvitationAcceptResponse:
    enforce_rate_limit(
        [
            RateLimitCheck(scope="invitations:public:accept", identity=ip_identity(request), rules=INVITATION_PUBLIC_ACCEPT_RULES),
            RateLimitCheck(scope="invitations:public:accept", identity=user_identity(current_user.id), rules=INVITATION_PUBLIC_ACCEPT_RULES),
        ]
    )
    invitation = _invitation_by_token(db, token)

    if invitation.organization.status == OrganizationStatus.suspended.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "organization_suspended",
                "message": "This organization is not currently accepting new members.",
            },
        )
    if get_effective_settings(db).maintenance_mode:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "maintenance_mode",
                "message": "The platform is currently undergoing maintenance. Please try again shortly.",
            },
        )

    try:
        membership = accept_invitation_record(db, invitation, current_user)
    except InvitationAlreadyAcceptedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invitation_already_accepted", "message": "This invitation has already been accepted."},
        )
    except InvitationExpiredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invitation_expired", "message": "This invitation has expired."},
        )
    except InvitationEmailMismatchError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "invitation_email_mismatch",
                "message": "This invitation was sent to a different email address.",
            },
        )
    except InvalidInvitationRoleError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "invitation_invalid",
                "message": "This invitation is no longer valid.",
            },
        )
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())

    organization = invitation.organization

    if invitation.inviter is not None and invitation.inviter.email:
        try:
            email_sender = get_email_sender()
            subject, body = build_invitation_accepted_email(organization, membership, invitation.inviter)
            email_sender.send(
                EmailMessage(to=invitation.inviter.email, subject=subject, text_body=body, attachments=[])
            )
        except (EmailSendError, HTTPException) as exc:
            # Optional, best-effort notification -- never blocks the
            # actual acceptance, which has already been committed.
            logger.warning(
                "accept_public_invitation: could not send accepted-notification "
                "organization_id=%s invitation_id=%s exception_type=%s",
                organization.id,
                invitation.id,
                type(exc).__name__,
            )

    return PublicInvitationAcceptResponse(
        organization_id=organization.id,
        organization_name=organization.business_name or organization.name,
        role=membership.role,
    )
