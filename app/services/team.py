"""Shared team/membership/invitation business logic.

Mirrors app.services.invoices/app.services.quotes's own rationale exactly:
typed exceptions instead of HTTPException (no FastAPI dependency, so both
a router and a future AI tool could translate them independently), every
function takes an explicit organization_id or an already org-scoped row,
never trusts a caller-supplied id without filtering on it.

Two families of invariant live here rather than in app.permissions's
static ROLE_PERMISSIONS map, because both are relational (actor rank vs.
target/requested rank) or data-dependent (current membership table state),
not "what can this role do in general":

1. Role hierarchy (app.role_hierarchy.can_manage_member / can_assign_role):
   an actor may never assign a role at or above their own rank (blocks
   self-promotion and admin-granting-admin/owner alike), and may never
   modify or remove another member whose current role is at or above
   their own rank (blocks admin-vs-admin and admin-vs-owner). Self-
   modification is exempt from the second rule by design -- see
   can_manage_member's docstring.
2. Ownership headcount: granting/revoking the "owner" role requires the
   *caller* to already be an owner (enforced today via can_manage_member's
   owner-vs-owner special case, since only an owner ever reaches that
   branch), and demoting or removing an owner additionally requires at
   least one *other* active owner to remain afterward
   (CannotRemoveLastOwnerError otherwise).
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
from app.role_hierarchy import can_assign_role, can_manage_member, parse_membership_role


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


class RoleAssignmentNotAllowedError(Exception):
    """The actor's rank isn't high enough to hand out the requested role
    -- covers "admin may assign only member or viewer" (never admin or
    owner) and "a user may never assign a role at or above their own,"
    which together also make self-promotion structurally impossible: see
    app.role_hierarchy.can_assign_role."""


class InsufficientRoleAuthorityError(Exception):
    """The actor's rank isn't high enough to modify or remove this
    *other* member, given the member's current role -- covers admin
    acting on another admin or on an owner. Never raised for a target
    that is the actor's own membership; see
    app.role_hierarchy.can_manage_member."""


class SelfPromotionError(Exception):
    """An owner may never grant ownership to their own membership --
    ownership can only ever be granted to someone else, even though every
    caller who can reach this action is already an owner and the action
    would otherwise be a harmless no-op."""


class InvalidRoleError(Exception):
    """A stored role value (actor's or target's) isn't a recognized
    MembershipRole -- hand-edited or corrupted data. Fails closed: no
    role/removal decision is ever made from data that can't be parsed."""


class InvalidInvitationRoleError(Exception):
    """An invitation's stored role isn't a recognized InvitationRole --
    hand-edited or corrupted data, or (defense in depth) a value that
    somehow bypassed InvitationCreateRequest's schema validation.
    Acceptance must never blindly trust a stale/tampered invitation row;
    this rejects it outright rather than materializing a membership with
    an unvalidated role."""


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
    removal does.

    Two hierarchy checks, in order: (1) can_assign_role -- would this
    grant new_role at or above the actor's own rank? Applies whether the
    target is someone else or the actor themself, which is exactly what
    makes self-promotion structurally impossible here, with no separate
    self-check needed. (2) can_manage_member -- for a target that is NOT
    the actor, is the actor senior enough to touch a member currently
    holding target's role at all (blocks admin-vs-admin, admin-vs-owner)?
    Skipped for self-targeting by design -- see that function's
    docstring."""
    actor_role = parse_membership_role(actor.role)
    if not can_assign_role(actor_role, MembershipRole(new_role.value)):
        raise RoleAssignmentNotAllowedError(actor.id)

    is_self = target_membership.user_id == actor.user_id
    if not is_self:
        target_role = parse_membership_role(target_membership.role)
        if not can_manage_member(actor_role, target_role):
            raise InsufficientRoleAuthorityError(actor.id)

    if _grants_ownership(target_membership.role):
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
    if target_membership.user_id == actor.user_id:
        # Every caller who reaches this line is already an owner (see
        # above), so granting ownership to themselves would be a harmless
        # no-op in practice -- rejected anyway, since "a user may never
        # promote themselves" is an absolute rule with no no-op exception.
        raise SelfPromotionError(actor.id)

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
    products) is entirely untouched -- nothing here cascades to them.

    The hierarchy check (can_manage_member, skipped for self -- a user may
    remove themselves) runs before the already-removed check, so an
    unauthorized actor never learns a target's removal state either."""
    actor_role = parse_membership_role(actor.role)
    is_self = target_membership.user_id == actor.user_id
    if not is_self:
        target_role = parse_membership_role(target_membership.role)
        if not can_manage_member(actor_role, target_role):
            raise InsufficientRoleAuthorityError(actor.id)

    if target_membership.status == MembershipStatus.removed.value:
        raise MemberAlreadyRemovedError(target_membership.id)
    if _grants_ownership(target_membership.role):
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
    (see app.routers.invitations); only its hash is ever persisted.

    The same can_assign_role check change_member_role_record uses gates
    the requested role here too -- an admin inviting someone as "admin"
    is exactly as disallowed as an admin promoting an existing member to
    "admin"; both are just "assign a role at or above your own rank"."""
    actor_role = parse_membership_role(actor.role)
    if not can_assign_role(actor_role, MembershipRole(role.value)):
        raise RoleAssignmentNotAllowedError(actor.id)

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
    try:
        InvitationRole(invitation.role)
    except ValueError:
        # Never blindly trust a stale/tampered invitation row -- a role
        # that isn't a recognized InvitationRole (hand-edited data, or a
        # value that somehow bypassed InvitationCreateRequest's schema
        # validation) must never materialize into a real membership.
        raise InvalidInvitationRoleError(invitation.id)

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
