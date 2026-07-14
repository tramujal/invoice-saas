import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.email.base import EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.email.invitation_templates import build_invitation_email
from app.invitation_tokens import build_invitation_link
from app.models import Organization, OrganizationInvitation, User
from app.permissions import Permission
from app.rate_limit import (
    INVITATION_CREATE_RULES,
    RateLimitCheck,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
from app.schemas import (
    InvitationCreateRequest,
    InvitationResponse,
    PaginatedInvitationsResponse,
)
from app.services.team import (
    AlreadyMemberError,
    InvitationAlreadyAcceptedError,
    InvitationAlreadyPendingError,
    cancel_invitation_record,
    invite_member_record,
    resend_invitation_record,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations/{organization_id}/invitations", tags=["invitations"])


def _invitation_or_404(db: Session, organization_id: str, invitation_id: str) -> OrganizationInvitation:
    invitation = db.scalar(
        select(OrganizationInvitation)
        .options(selectinload(OrganizationInvitation.inviter))
        .where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.organization_id == organization_id,
        )
    )
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return invitation


def _send_invitation_email(invitation: OrganizationInvitation, organization: Organization, raw_token: str) -> None:
    email_sender = get_email_sender()
    accept_link = build_invitation_link(raw_token)
    subject, body = build_invitation_email(invitation, organization, invitation.inviter, accept_link)
    message = EmailMessage(to=invitation.email, subject=subject, text_body=body, attachments=[])

    logger.info(
        "send_invitation_email: sending organization_id=%s invitation_id=%s",
        organization.id,
        invitation.id,
    )
    try:
        email_sender.send(message)
    except EmailSendError as exc:
        logger.error(
            "send_invitation_email: failed organization_id=%s invitation_id=%s "
            "exception_type=%s exception_message=%s",
            organization.id,
            invitation.id,
            type(exc).__name__,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send invitation email. Please try again later.",
        )


@router.get("", response_model=PaginatedInvitationsResponse)
def list_invitations(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedInvitationsResponse:
    require_permission(current_user, organization_id, Permission.members_manage, db)
    rows = list(
        db.scalars(
            select(OrganizationInvitation)
            .options(selectinload(OrganizationInvitation.inviter))
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.accepted_at.is_(None),
            )
            .order_by(OrganizationInvitation.created_at.desc())
        ).all()
    )
    return PaginatedInvitationsResponse(total=len(rows), items=rows)


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
def create_invitation(
    organization_id: str,
    body: InvitationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvitationResponse:
    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="invitations:create:user",
                identity=user_identity(current_user.id),
                rules=INVITATION_CREATE_RULES,
            ),
            RateLimitCheck(
                scope="invitations:create:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=INVITATION_CREATE_RULES,
            ),
        ]
    )

    actor = require_permission(current_user, organization_id, Permission.members_manage, db)
    require_verified_email(current_user)

    organization = db.get(Organization, organization_id)

    try:
        invitation, raw_token = invite_member_record(db, organization_id, body.email, body.role, actor)
    except AlreadyMemberError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "already_member", "message": "This email already belongs to an active member."},
        )
    except InvitationAlreadyPendingError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "invitation_already_pending",
                "message": "An invitation is already pending for this email. Resend it instead.",
            },
        )

    _send_invitation_email(invitation, organization, raw_token)
    return invitation


@router.post("/{invitation_id}/resend", response_model=InvitationResponse)
def resend_invitation(
    organization_id: str,
    invitation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvitationResponse:
    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="invitations:create:user",
                identity=user_identity(current_user.id),
                rules=INVITATION_CREATE_RULES,
            ),
            RateLimitCheck(
                scope="invitations:create:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=INVITATION_CREATE_RULES,
            ),
        ]
    )

    require_permission(current_user, organization_id, Permission.members_manage, db)
    require_verified_email(current_user)

    organization = db.get(Organization, organization_id)
    invitation = _invitation_or_404(db, organization_id, invitation_id)

    try:
        invitation, raw_token = resend_invitation_record(db, invitation)
    except InvitationAlreadyAcceptedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invitation_already_accepted", "message": "This invitation has already been accepted."},
        )

    _send_invitation_email(invitation, organization, raw_token)
    return invitation


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_invitation(
    organization_id: str,
    invitation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_permission(current_user, organization_id, Permission.members_manage, db)
    require_verified_email(current_user)
    invitation = _invitation_or_404(db, organization_id, invitation_id)
    cancel_invitation_record(db, invitation)
