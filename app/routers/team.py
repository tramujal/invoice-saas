from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member, require_permission, require_verified_email
from app.membership_role import InvitationRole
from app.models import User
from app.permissions import Permission
from app.schemas import (
    GrantOwnershipRequest,
    MemberResponse,
    MembershipRoleUpdateRequest,
    PaginatedMembersResponse,
)
from app.services.team import (
    CannotGrantOwnershipError,
    CannotRemoveLastOwnerError,
    ConfirmationRequiredError,
    MemberAlreadyRemovedError,
    MembershipNotFoundError,
    change_member_role_record,
    get_membership_in_org,
    grant_ownership_record,
    list_members_in_org,
    remove_member_record,
)

router = APIRouter(prefix="/organizations/{organization_id}/members", tags=["team"])


def _membership_or_404(db: Session, organization_id: str, membership_id: str):
    try:
        return get_membership_in_org(db, organization_id, membership_id)
    except MembershipNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")


@router.get("", response_model=PaginatedMembersResponse)
def list_members(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedMembersResponse:
    # Deliberately require_org_member only, not members.manage -- a team
    # roster isn't secret from teammates, matching the existing convention
    # that low-sensitivity reads (dashboard, insights) are membership-
    # gated only, not role-gated.
    require_org_member(current_user, organization_id, db)
    members = list_members_in_org(db, organization_id)
    return PaginatedMembersResponse(total=len(members), items=members)


@router.patch("/{membership_id}", response_model=MemberResponse)
def update_member_role(
    organization_id: str,
    membership_id: str,
    body: MembershipRoleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemberResponse:
    actor = require_permission(current_user, organization_id, Permission.members_manage, db)
    require_verified_email(current_user)
    target = _membership_or_404(db, organization_id, membership_id)

    try:
        return change_member_role_record(db, organization_id, target, body.role, actor)
    except CannotGrantOwnershipError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "owner_action_required",
                "message": "Only an owner can change another owner's role.",
            },
        )
    except CannotRemoveLastOwnerError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "cannot_remove_last_owner",
                "message": "This organization must always have at least one owner.",
            },
        )


@router.post("/{membership_id}/remove", response_model=MemberResponse)
def remove_member(
    organization_id: str,
    membership_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemberResponse:
    actor = require_permission(current_user, organization_id, Permission.members_manage, db)
    require_verified_email(current_user)
    target = _membership_or_404(db, organization_id, membership_id)

    try:
        return remove_member_record(db, organization_id, target, actor)
    except CannotGrantOwnershipError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "owner_action_required",
                "message": "Only an owner can remove another owner.",
            },
        )
    except CannotRemoveLastOwnerError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "cannot_remove_last_owner",
                "message": "This organization must always have at least one owner.",
            },
        )
    except MemberAlreadyRemovedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "member_already_removed", "message": "This member has already been removed."},
        )


@router.post("/{membership_id}/grant-ownership", response_model=MemberResponse)
def grant_ownership(
    organization_id: str,
    membership_id: str,
    body: GrantOwnershipRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemberResponse:
    # organization.manage -- owner-only, distinct from members.manage
    # (which owner+admin both hold) -- granting ownership is the single
    # most consequential action in this feature.
    actor = require_permission(current_user, organization_id, Permission.organization_manage, db)
    require_verified_email(current_user)
    target = _membership_or_404(db, organization_id, membership_id)

    try:
        return grant_ownership_record(db, organization_id, target, actor, body.confirm)
    except ConfirmationRequiredError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "confirmation_required", "message": "Granting ownership requires confirm=true."},
        )
    except CannotGrantOwnershipError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "owner_action_required", "message": "Only an owner can grant ownership."},
        )
