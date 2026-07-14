"""Shared team/membership analytics queries -- used by the dashboard
router (app/routers/dashboard.py), the Business Insights engine
(app/insights/engine.py), and the AI assistant's context builder
(app/assistant_context.py). Mirrors app.quote_analytics's exact "shared by
dashboard + insights + assistant" precedent: one query, more than one
caller, never duplicated.

Every count/list here is scoped to active=True memberships (or, for
invitations, still-pending ones) -- a soft-removed member or a cancelled/
accepted invitation is never counted as current team state.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.membership_role import MembershipRole
from app.membership_status import MembershipStatus
from app.models import OrganizationInvitation, OrganizationMember
from app.permissions import Permission, roles_with_permission

RECENT_MEMBERS_WINDOW_DAYS = 30
PENDING_INVITATIONS_LIMIT = 10
RECENT_MEMBERS_LIMIT = 10


@dataclass
class TeamRoleCountData:
    role: MembershipRole
    count: int


@dataclass
class TeamSummaryData:
    total_members: int
    by_role: list[TeamRoleCountData]
    owner_count: int
    pending_invitations: int


def get_team_summary(db: Session, organization_id: str) -> TeamSummaryData:
    rows = db.execute(
        select(OrganizationMember.role, func.count())
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == MembershipStatus.active.value,
        )
        .group_by(OrganizationMember.role)
    ).all()
    counts_by_role = {role: count for role, count in rows}
    total_members = sum(counts_by_role.values())
    # "Owner" here means owner-equivalent (holds organization.manage), the
    # same permission app.services.team's "at least one owner" invariant
    # keys off -- not a hardcoded role name, so this stays correct if a
    # future custom role is also granted organization.manage.
    owner_count = sum(
        counts_by_role.get(role.value, 0) for role in roles_with_permission(Permission.organization_manage)
    )

    pending_invitations = (
        db.scalar(
            select(func.count())
            .select_from(OrganizationInvitation)
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.accepted_at.is_(None),
            )
        )
        or 0
    )

    by_role = [
        TeamRoleCountData(role=role, count=counts_by_role.get(role.value, 0))
        for role in MembershipRole
    ]

    return TeamSummaryData(
        total_members=total_members,
        by_role=by_role,
        owner_count=owner_count,
        pending_invitations=pending_invitations,
    )


@dataclass
class PendingInvitationInfo:
    email: str
    role: str
    invited_by_email: str | None
    created_at: datetime


def get_pending_invitations(
    db: Session, organization_id: str, limit: int = PENDING_INVITATIONS_LIMIT
) -> list[PendingInvitationInfo]:
    rows = db.scalars(
        select(OrganizationInvitation)
        .options(selectinload(OrganizationInvitation.inviter))
        .where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.accepted_at.is_(None),
        )
        .order_by(OrganizationInvitation.created_at.desc())
        .limit(limit)
    ).all()
    return [
        PendingInvitationInfo(
            email=row.email,
            role=row.role,
            invited_by_email=row.created_by_email,
            created_at=row.created_at,
        )
        for row in rows
    ]


@dataclass
class RecentMemberInfo:
    user_email: str
    role: str
    invited_by_email: str | None
    accepted_at: datetime


def get_recent_accepted_members(
    db: Session,
    organization_id: str,
    days: int = RECENT_MEMBERS_WINDOW_DAYS,
    limit: int = RECENT_MEMBERS_LIMIT,
) -> list[RecentMemberInfo]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.scalars(
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.user), selectinload(OrganizationMember.inviter))
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == MembershipStatus.active.value,
            OrganizationMember.accepted_at >= cutoff,
        )
        .order_by(OrganizationMember.accepted_at.desc())
        .limit(limit)
    ).all()
    return [
        RecentMemberInfo(
            user_email=row.user_email,
            role=row.role,
            invited_by_email=row.invited_by_email,
            accepted_at=row.accepted_at,
        )
        for row in rows
    ]
