"""Shared team/membership/invitation business logic.

Mirrors app.services.invoices/app.services.quotes's own rationale exactly:
typed exceptions instead of HTTPException (no FastAPI dependency, so both
a router and a future AI tool could translate them independently), every
function takes an explicit organization_id or an already org-scoped row,
never trusts a caller-supplied id without filtering on it.

The two invariants a single Permission check can't express live here:
granting/revoking the "owner" role requires the *caller* to already be an
owner (CannotGrantOwnershipError otherwise), and demoting or removing an
owner additionally requires at least one *other* active owner to remain
afterward (CannotRemoveLastOwnerError otherwise). Both are data-dependent
facts about the current membership table, not static role facts, which is
why they can't live in app.permissions's static ROLE_PERMISSIONS map.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.invitation_tokens import (
    INVITATION_TOKEN_TTL_HOURS,
    generate_invitation_token,
    hash_invitation_token,
)
from app.membership_role import InvitationRole, MembershipRole
from app.membership_status import MembershipStatus
from app.models import Organization, OrganizationInvitation, OrganizationMember, User
from app.permissions import Permission, check_permission, roles_with_permission


class MembershipNotFoundError(Exception):
    """No active membership matches the given id within this organization."""


class InvitationNotFoundError(Exception):
    """No invitation matches the given id/token within this organization."""


class InvitationExpiredError(Exception):
    pass


class InvitationAlreadyAcceptedError(Exception):
    pass


class InvitationAlreadyPendingError(Exception):
    """A pending (not yet accepted) invitation already exists for this
    (organization_id, email) -- the caller should resend it instead of
    creating a duplicate."""


class InvitationEmailMismatchError(Exception):
    """The authenticated user's email doesn't match the invitation's --
    can't accept someone else's invitation even while logged in."""


class CannotRemoveLastOwnerError(Exception):
    """The change would leave this organization with zero active owners."""


class CannotGrantOwnershipError(Exception):
    """Only an existing owner may grant ownership to someone else, or
    demote/remove an existing owner."""


class AlreadyMemberError(Exception):
    """The invited email already belongs to an active member of this org."""


class MemberAlreadyRemovedError(Exception):
    pass


class ConfirmationRequiredError(Exception):
    """Granting ownership requires an explicit confirm=True in the request."""


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True)
    # columns (Postgres returns aware ones) -- normalize before comparing,
    # same convention as app/routers/assistant_actions.py's _aware.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _grants_ownership(role: str) -> bool:
    """Whether this role counts as "owner-equivalent" for the ownership
    invariants below -- driven entirely by app.permissions.ROLE_PERMISSIONS
    (via check_permission), never a hardcoded role name. A future custom
    role granted organization.manage participates in these invariants
    automatically, with no change needed here."""
    return check_permission(MembershipRole(role), Permission.organization_manage)


def _count_members_with_permission(
    db: Session,
    organization_id: str,
    permission: Permission,
    exclude_membership_id: str | None = None,
) -> int:
    """How many active members currently hold `permission`, derived from
    which roles grant it (app.permissions.roles_with_permission) -- never a
    specific role name. Used for the "at least one owner" invariant today
    (permission=organization.manage), but generic enough for any future
    permission-gated headcount invariant."""
    role_values = [role.value for role in roles_with_permission(permission)]
    query = select(func.count()).select_from(OrganizationMember).where(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.status == MembershipStatus.active.value,
        OrganizationMember.role.in_(role_values),
    )
    if exclude_membership_id is not None:
        query = query.where(OrganizationMember.id != exclude_membership_id)
    return db.scalar(query) or 0


def list_members_in_org(db: Session, organization_id: str) -> list[OrganizationMember]:
    return list(
        db.scalars(
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user), selectinload(OrganizationMember.inviter))
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.status == MembershipStatus.active.value,
            )
            .order_by(OrganizationMember.created_at.asc())
        ).all()
    )


def get_membership_in_org(
    db: Session, organization_id: str, membership_id: str
) -> OrganizationMember:
    membership = db.scalar(
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.user), selectinload(OrganizationMember.inviter))
        .where(
            OrganizationMember.id == membership_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == MembershipStatus.active.value,
        )
    )
    if membership is None:
        raise MembershipNotFoundError(membership_id)
    return membership


def change_member_role_record(
    db: Session,
    organization_id: str,
    target_membership: OrganizationMember,
    new_role: InvitationRole,
    actor: OrganizationMember,
) -> OrganizationMember:
    """Ordinary admin/member/viewer transitions. new_role is always
    InvitationRole (never "owner" -- see that enum's docstring), but
    target_membership's CURRENT role may already be owner-equivalent, in
    which case this is a demotion and gets the same owner-count guard
    removal does."""
    if _grants_ownership(target_membership.role):
        if not _grants_ownership(actor.role):
            raise CannotGrantOwnershipError(actor.id)
        if (
            _count_members_with_permission(
                db, organization_id, Permission.organization_manage, exclude_membership_id=target_membership.id
            )
            < 1
        ):
            raise CannotRemoveLastOwnerError(target_membership.id)

    target_membership.role = new_role.value
    target_membership.role_changed_by = actor.user_id
    db.commit()
    db.refresh(target_membership)
    return target_membership


def grant_ownership_record(
    db: Session,
    organization_id: str,
    target_membership: OrganizationMember,
    actor: OrganizationMember,
    confirm: bool,
) -> OrganizationMember:
    """The dedicated "Transfer Ownership" / "Grant Ownership" action --
    the only path through which role="owner" can ever be set. Multiple
    members may hold "owner" simultaneously; this never demotes the actor
    or anyone else, it only ever promotes the target. The literal "owner"
    role assignment below is this action's actual business effect (what it
    means to "grant ownership"), not an authorization decision -- the
    decision of *who may call this at all* is the organization.manage
    permission check above, matching every other action in this file."""
    if not confirm:
        raise ConfirmationRequiredError()
    if not _grants_ownership(actor.role):
        raise CannotGrantOwnershipError(actor.id)

    target_membership.role = MembershipRole.owner.value
    target_membership.role_changed_by = actor.user_id
    db.commit()
    db.refresh(target_membership)
    return target_membership


def remove_member_record(
    db: Session,
    organization_id: str,
    target_membership: OrganizationMember,
    actor: OrganizationMember,
) -> OrganizationMember:
    """Soft removal only -- status flips to removed, the row (and its
    invited_by/accepted_at audit trail) is kept forever. Every business
    record the removed member ever created (invoices, quotes, customers,
    products) is entirely untouched -- nothing here cascades to them."""
    if target_membership.status == MembershipStatus.removed.value:
        raise MemberAlreadyRemovedError(target_membership.id)
    if _grants_ownership(target_membership.role):
        if not _grants_ownership(actor.role):
            raise CannotGrantOwnershipError(actor.id)
        if (
            _count_members_with_permission(
                db, organization_id, Permission.organization_manage, exclude_membership_id=target_membership.id
            )
            < 1
        ):
            raise CannotRemoveLastOwnerError(target_membership.id)

    target_membership.status = MembershipStatus.removed.value
    target_membership.removed_by = actor.user_id
    db.commit()
    db.refresh(target_membership)
    return target_membership


def invite_member_record(
    db: Session, organization_id: str, email: str, role: InvitationRole, actor: OrganizationMember
) -> tuple[OrganizationInvitation, str]:
    """Returns (invitation, raw_token) -- the raw token exists only in
    memory for exactly long enough to build the invitation email link
    (see app.routers.invitations); only its hash is ever persisted."""
    existing_member = db.scalar(
        select(OrganizationMember)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == MembershipStatus.active.value,
            User.email == email,
        )
    )
    if existing_member is not None:
        raise AlreadyMemberError(email)

    existing_invitation = db.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.accepted_at.is_(None),
        )
    )
    if existing_invitation is not None:
        raise InvitationAlreadyPendingError(email)

    raw_token = generate_invitation_token()
    invitation = OrganizationInvitation(
        organization_id=organization_id,
        email=email,
        role=role.value,
        token_hash=hash_invitation_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITATION_TOKEN_TTL_HOURS),
        created_by=actor.user_id,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation, raw_token


def resend_invitation_record(
    db: Session, invitation: OrganizationInvitation
) -> tuple[OrganizationInvitation, str]:
    """Rotates token_hash/expires_at on the same row -- the old token is
    immediately invalid, guaranteeing at most one valid token per pending
    invitation at any time."""
    if invitation.accepted_at is not None:
        raise InvitationAlreadyAcceptedError(invitation.id)

    raw_token = generate_invitation_token()
    invitation.token_hash = hash_invitation_token(raw_token)
    invitation.expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITATION_TOKEN_TTL_HOURS)
    db.commit()
    db.refresh(invitation)
    return invitation, raw_token


def cancel_invitation_record(db: Session, invitation: OrganizationInvitation) -> None:
    """Hard delete -- an un-accepted invitation carries no history worth
    keeping, unlike removing a real member."""
    db.delete(invitation)
    db.commit()


def get_invitation_by_token(db: Session, raw_token: str) -> OrganizationInvitation:
    invitation = db.scalar(
        select(OrganizationInvitation)
        .options(selectinload(OrganizationInvitation.organization), selectinload(OrganizationInvitation.inviter))
        .where(OrganizationInvitation.token_hash == hash_invitation_token(raw_token))
    )
    if invitation is None:
        raise InvitationNotFoundError(raw_token)
    return invitation


def accept_invitation_record(
    db: Session, invitation: OrganizationInvitation, current_user: User
) -> OrganizationMember:
    """Verifies expiry/single-use/email-match, then creates (or
    reactivates a previously-removed) OrganizationMember row. Marking
    invitation.accepted_at is this table's entire single-use guarantee --
    the same hash can never satisfy get_invitation_by_token's "pending"
    condition again."""
    now = datetime.now(timezone.utc)
    if invitation.accepted_at is not None:
        raise InvitationAlreadyAcceptedError(invitation.id)
    if _aware(invitation.expires_at) < now:
        raise InvitationExpiredError(invitation.id)
    if current_user.email.strip().lower() != invitation.email.strip().lower():
        raise InvitationEmailMismatchError(invitation.id)

    existing = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.organization_id == invitation.organization_id,
        )
    )
    if existing is not None and existing.status == MembershipStatus.active.value:
        # Already an active member (e.g. invited twice, or joined through
        # another path before accepting) -- nothing to change, just
        # consume the invitation so it can't be used again.
        membership = existing
    elif existing is not None:
        # Reactivating a previously-removed membership -- a fresh
        # acceptance, so role_changed_by/removed_by are cleared rather
        # than carrying over stale history from before removal.
        existing.role = invitation.role
        existing.status = MembershipStatus.active.value
        existing.invited_by = invitation.created_by
        existing.invited_at = invitation.created_at
        existing.accepted_at = now
        existing.role_changed_by = None
        existing.removed_by = None
        membership = existing
    else:
        membership = OrganizationMember(
            user_id=current_user.id,
            organization_id=invitation.organization_id,
            role=invitation.role,
            status=MembershipStatus.active.value,
            invited_by=invitation.created_by,
            invited_at=invitation.created_at,
            accepted_at=now,
        )
        db.add(membership)

    invitation.accepted_at = now
    db.commit()
    db.refresh(membership)
    return membership
