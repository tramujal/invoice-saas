"""Platform-administration endpoints -- see app.platform_permissions for
the authorization model (a completely separate axis from the per-org
Permission/require_permission system every other router uses).

Deliberately mounted at /admin, not under /organizations/{organization_id},
since nothing here is scoped to a single tenant: every query below
explicitly reads across all organizations, on purpose, and must never be
confused with (or share a helper with) the tenant-scoped get_X_in_org
lookups used everywhere else in this codebase.

Mostly read-only; Phase 13D adds the one mutation this file will ever
need for organizations -- suspend/reactivate (see
app.organization_status.OrganizationStatus). User management actions,
settings changes, role assignment, support mode, and organization
deletion remain out of scope. See each response schema in app.schemas for
exactly which fields are real stored columns vs. documented derivations
-- in particular, organization/user "created_at" is approximated from
the earliest active membership row, since neither Organization nor User
has its own created_at column, and there is deliberately no
"last_login_at" (never tracked anywhere).
"""

import os
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from app.ai.factory import is_ai_configured
from app.assistant_action_status import AssistantActionStatus
from app.database import get_db
from app.deps import get_current_user, require_platform_permission
from app.invoice_numbering import format_invoice_number
from app.membership_role import MembershipRole
from app.membership_status import MembershipStatus
from app.models import (
    PLATFORM_SETTINGS_SINGLETON_ID,
    AssistantAction,
    Customer,
    Invoice,
    InvoiceReminder,
    Organization,
    OrganizationMember,
    PlatformAuditLog,
    PlatformSettings,
    Product,
    Quote,
    QuoteReminder,
    User,
)
from app.organization_status import OrganizationStatus
from app.platform_audit_action import PlatformAuditAction
from app.platform_audit_sanitize import mask_client_ip, sanitize_audit_details
from app.platform_permissions import PlatformPermission, PlatformRole
from app.quote_numbering import format_quote_number
from app.rate_limit import get_client_ip
from app.reminder_status import ReminderStatus
from app.routers.auth import issue_password_reset
from app.schemas import (
    PaginatedPlatformAuditLogResponse,
    PaginatedPlatformOrganizationsResponse,
    PaginatedPlatformUsersResponse,
    PlatformAuditLogEntry,
    PlatformDashboardResponse,
    PlatformOrganizationActionRequest,
    PlatformOrganizationDetail,
    PlatformOrganizationMember,
    PlatformOrganizationRecentDocument,
    PlatformOrganizationSummary,
    PlatformRoleActionRequest,
    PlatformSettingsResponse,
    PlatformSettingsUpdateRequest,
    PlatformSystemHealthResponse,
    PlatformUserActionRequest,
    PlatformUserActionResponse,
    PlatformUserDetail,
    PlatformUserOrganization,
    PlatformUserSummary,
)
from app.services.platform_audit import record_organization_action, record_settings_action, record_user_action
from app.services.platform_settings import get_effective_settings, get_or_create_settings_row
from app.user_status import UserStatus

router = APIRouter(prefix="/admin", tags=["platform-admin"])

RECENT_DOCUMENTS_LIMIT = 5
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


# --- Cross-org aggregation helpers -----------------------------------
#
# Every helper below intentionally has NO organization_id parameter and
# never calls a get_X_in_org tenant-scoped lookup -- that absence is the
# visible signal that this file's queries are cross-tenant by
# construction, not a bug.


def _org_created_at_map(db: Session, organization_ids: list[str]) -> dict[str, datetime]:
    """Approximates each organization's creation time as its earliest
    active membership's created_at -- an organization and its first owner
    membership are created together in one transaction at registration,
    so this is a faithful proxy, not a guess. Organization itself has no
    created_at column."""
    if not organization_ids:
        return {}
    rows = db.execute(
        select(OrganizationMember.organization_id, func.min(OrganizationMember.created_at))
        .where(OrganizationMember.organization_id.in_(organization_ids))
        .group_by(OrganizationMember.organization_id)
    ).all()
    return dict(rows)


def _user_created_at_map(db: Session, user_ids: list[str]) -> dict[str, datetime]:
    """Same proxy as _org_created_at_map, grouped by user instead --
    every user created through the existing registration/invitation
    flows ends up with at least one membership at the same moment."""
    if not user_ids:
        return {}
    rows = db.execute(
        select(OrganizationMember.user_id, func.min(OrganizationMember.created_at))
        .where(OrganizationMember.user_id.in_(user_ids))
        .group_by(OrganizationMember.user_id)
    ).all()
    return dict(rows)


def _count_new_since(db: Session, group_column, since: datetime) -> int:
    """Counts distinct groups (organizations or users, depending on
    group_column) whose earliest membership row falls on/after `since` --
    the same creation-time proxy as the maps above, aggregated."""
    subq = (
        select(group_column, func.min(OrganizationMember.created_at).label("first_at"))
        .group_by(group_column)
        .subquery()
    )
    return db.scalar(select(func.count()).select_from(subq).where(subq.c.first_at >= since)) or 0


def _count_by_org(db: Session, model, organization_ids: list[str]) -> dict[str, int]:
    if not organization_ids:
        return {}
    rows = db.execute(
        select(model.organization_id, func.count())
        .where(model.organization_id.in_(organization_ids))
        .group_by(model.organization_id)
    ).all()
    return dict(rows)


def _active_member_count_by_org(db: Session, organization_ids: list[str]) -> dict[str, int]:
    if not organization_ids:
        return {}
    rows = db.execute(
        select(OrganizationMember.organization_id, func.count())
        .where(
            OrganizationMember.organization_id.in_(organization_ids),
            OrganizationMember.status == MembershipStatus.active.value,
        )
        .group_by(OrganizationMember.organization_id)
    ).all()
    return dict(rows)


def _owner_email_map(db: Session, organization_ids: list[str]) -> dict[str, str]:
    """The earliest-accepted active owner's email per org -- an org can
    have multiple simultaneous owners (see OrganizationMember's own
    docstring), so this picks one deterministically rather than exposing
    a list where the summary view only has room for one."""
    if not organization_ids:
        return {}
    rows = db.execute(
        select(OrganizationMember.organization_id, User.email, OrganizationMember.accepted_at)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id.in_(organization_ids),
            OrganizationMember.role == MembershipRole.owner.value,
            OrganizationMember.status == MembershipStatus.active.value,
        )
    ).all()
    earliest: dict[str, datetime] = {}
    result: dict[str, str] = {}
    for org_id, email, accepted_at in rows:
        if org_id not in earliest or accepted_at < earliest[org_id]:
            earliest[org_id] = accepted_at
            result[org_id] = email
    return result


def _last_activity_map(db: Session, organization_ids: list[str]) -> dict[str, datetime]:
    """The most recent created_at across an org's invoices/quotes/
    customers/products -- a real, defensible "last activity" signal,
    since no dedicated activity-log table exists."""
    if not organization_ids:
        return {}
    result: dict[str, datetime] = {}
    for model in (Invoice, Quote, Customer, Product):
        rows = db.execute(
            select(model.organization_id, func.max(model.created_at))
            .where(model.organization_id.in_(organization_ids))
            .group_by(model.organization_id)
        ).all()
        for org_id, max_at in rows:
            if max_at is not None and (org_id not in result or max_at > result[org_id]):
                result[org_id] = max_at
    return result


def _organizations_count_by_user(db: Session, user_ids: list[str]) -> dict[str, int]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(OrganizationMember.user_id, func.count())
        .where(
            OrganizationMember.user_id.in_(user_ids),
            OrganizationMember.status == MembershipStatus.active.value,
        )
        .group_by(OrganizationMember.user_id)
    ).all()
    return dict(rows)


def _count_reminders(db: Session, model, reminder_status: ReminderStatus, since: datetime | None = None) -> int:
    conditions = [model.status == reminder_status.value]
    if since is not None:
        conditions.append(model.created_at >= since)
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def _email_provider_status() -> tuple[bool, str | None]:
    """Mirrors app.email.factory.get_email_sender's own configured-check
    (RESEND_API_KEY + EMAIL_FROM both present) without actually
    constructing a sender or logging -- this is a passive health read,
    never a trigger to warn about missing config."""
    configured = bool(os.environ.get("RESEND_API_KEY")) and bool(os.environ.get("EMAIL_FROM"))
    return configured, ("resend" if configured else None)


def _ai_provider_name() -> str:
    """Mirrors app.ai.factory's own default ("anthropic" when AI_PROVIDER
    is unset) -- always called alongside is_ai_configured()."""
    return (os.environ.get("AI_PROVIDER") or "anthropic").strip().lower()


def _cors_allowed_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or _DEFAULT_CORS_ORIGINS


def _system_health(db: Session) -> PlatformSystemHealthResponse:
    try:
        db.execute(text("SELECT 1"))
        database_reachable = True
    except Exception:
        database_reachable = False

    email_configured, email_provider = _email_provider_status()
    ai_configured = is_ai_configured()
    ai_provider = _ai_provider_name() if ai_configured else None

    since_7d = datetime.now(timezone.utc) - timedelta(days=7)
    pending = _count_reminders(db, InvoiceReminder, ReminderStatus.pending) + _count_reminders(
        db, QuoteReminder, ReminderStatus.pending
    )
    sent_7d = _count_reminders(db, InvoiceReminder, ReminderStatus.sent, since_7d) + _count_reminders(
        db, QuoteReminder, ReminderStatus.sent, since_7d
    )
    failed_7d = _count_reminders(db, InvoiceReminder, ReminderStatus.failed, since_7d) + _count_reminders(
        db, QuoteReminder, ReminderStatus.failed, since_7d
    )

    return PlatformSystemHealthResponse(
        database_reachable=database_reachable,
        email_provider_configured=email_configured,
        email_provider=email_provider,
        ai_provider_configured=ai_configured,
        ai_provider=ai_provider,
        reminder_emails_pending=pending,
        reminder_emails_sent_7d=sent_7d,
        reminder_emails_failed_7d=failed_7d,
    )


@router.get("/dashboard", response_model=PlatformDashboardResponse)
def get_platform_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformDashboardResponse:
    require_platform_permission(current_user, PlatformPermission.dashboard_view)

    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    organizations_total = db.scalar(select(func.count()).select_from(Organization)) or 0
    users_total = db.scalar(select(func.count()).select_from(User)) or 0
    invoices_total = db.scalar(select(func.count()).select_from(Invoice)) or 0
    quotes_total = db.scalar(select(func.count()).select_from(Quote)) or 0
    customers_total = db.scalar(select(func.count()).select_from(Customer)) or 0
    products_total = db.scalar(select(func.count()).select_from(Product)) or 0

    reminder_emails_sent_7d = _count_reminders(
        db, InvoiceReminder, ReminderStatus.sent, since_7d
    ) + _count_reminders(db, QuoteReminder, ReminderStatus.sent, since_7d)
    reminder_emails_failed_7d = _count_reminders(
        db, InvoiceReminder, ReminderStatus.failed, since_7d
    ) + _count_reminders(db, QuoteReminder, ReminderStatus.failed, since_7d)

    ai_actions_executed_7d = (
        db.scalar(
            select(func.count())
            .select_from(AssistantAction)
            .where(
                AssistantAction.status == AssistantActionStatus.executed.value,
                AssistantAction.executed_at >= since_7d,
            )
        )
        or 0
    )

    return PlatformDashboardResponse(
        organizations_total=organizations_total,
        organizations_new_7d=_count_new_since(db, OrganizationMember.organization_id, since_7d),
        organizations_new_30d=_count_new_since(db, OrganizationMember.organization_id, since_30d),
        users_total=users_total,
        users_new_7d=_count_new_since(db, OrganizationMember.user_id, since_7d),
        users_new_30d=_count_new_since(db, OrganizationMember.user_id, since_30d),
        invoices_total=invoices_total,
        quotes_total=quotes_total,
        customers_total=customers_total,
        products_total=products_total,
        reminder_emails_sent_7d=reminder_emails_sent_7d,
        reminder_emails_failed_7d=reminder_emails_failed_7d,
        ai_actions_executed_7d=ai_actions_executed_7d,
        health=_system_health(db),
    )


@router.get("/organizations", response_model=PaginatedPlatformOrganizationsResponse)
def list_platform_organizations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255),
) -> PaginatedPlatformOrganizationsResponse:
    require_platform_permission(current_user, PlatformPermission.organizations_view)

    base_query = select(Organization)
    if search and search.strip():
        term = f"%{search.strip()}%"
        base_query = base_query.where(
            or_(Organization.name.ilike(term), Organization.business_name.ilike(term))
        )

    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0

    orgs = db.scalars(base_query.order_by(Organization.name.asc()).limit(limit).offset(offset)).all()
    org_ids = [org.id for org in orgs]

    members_by_org = _active_member_count_by_org(db, org_ids)
    invoices_by_org = _count_by_org(db, Invoice, org_ids)
    quotes_by_org = _count_by_org(db, Quote, org_ids)
    customers_by_org = _count_by_org(db, Customer, org_ids)
    owner_email_by_org = _owner_email_map(db, org_ids)
    created_at_by_org = _org_created_at_map(db, org_ids)
    last_activity_by_org = _last_activity_map(db, org_ids)

    items = [
        PlatformOrganizationSummary(
            id=org.id,
            name=org.name,
            business_name=org.business_name,
            status=OrganizationStatus(org.status),
            owner_email=owner_email_by_org.get(org.id),
            members_count=members_by_org.get(org.id, 0),
            invoices_count=invoices_by_org.get(org.id, 0),
            quotes_count=quotes_by_org.get(org.id, 0),
            customers_count=customers_by_org.get(org.id, 0),
            created_at=created_at_by_org.get(org.id),
            last_activity_at=last_activity_by_org.get(org.id),
        )
        for org in orgs
    ]
    return PaginatedPlatformOrganizationsResponse(total=total, items=items)


def _organization_or_404(db: Session, organization_id: str) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


def _build_organization_detail(db: Session, organization: Organization) -> PlatformOrganizationDetail:
    """Shared by the plain GET detail endpoint and the suspend/reactivate
    mutations -- both need to return the exact same shape, and the
    mutation endpoints return it directly so the frontend never needs a
    second round-trip just to see its own result."""
    org_ids = [organization.id]
    members_count = _active_member_count_by_org(db, org_ids).get(organization.id, 0)
    invoices_count = _count_by_org(db, Invoice, org_ids).get(organization.id, 0)
    quotes_count = _count_by_org(db, Quote, org_ids).get(organization.id, 0)
    customers_count = _count_by_org(db, Customer, org_ids).get(organization.id, 0)
    products_count = _count_by_org(db, Product, org_ids).get(organization.id, 0)
    owner_email = _owner_email_map(db, org_ids).get(organization.id)
    created_at = _org_created_at_map(db, org_ids).get(organization.id)
    last_activity_at = _last_activity_map(db, org_ids).get(organization.id)

    member_rows = db.execute(
        select(OrganizationMember, User.email)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization.id)
        .order_by(OrganizationMember.created_at.asc())
    ).all()
    members = [
        PlatformOrganizationMember(
            user_id=membership.user_id,
            email=email,
            role=membership.role,
            status=membership.status,
            joined_at=membership.accepted_at,
        )
        for membership, email in member_rows
    ]

    recent_invoices = db.scalars(
        select(Invoice)
        .where(Invoice.organization_id == organization.id)
        .order_by(Invoice.created_at.desc())
        .limit(RECENT_DOCUMENTS_LIMIT)
    ).all()
    recent_quotes = db.scalars(
        select(Quote)
        .where(Quote.organization_id == organization.id)
        .order_by(Quote.created_at.desc())
        .limit(RECENT_DOCUMENTS_LIMIT)
    ).all()

    recent_documents = [
        PlatformOrganizationRecentDocument(
            type="invoice",
            number=format_invoice_number(inv.invoice_number),
            status=inv.effective_payment_status.value,
            total=inv.total,
            currency_code=inv.currency_code,
            created_at=inv.created_at,
        )
        for inv in recent_invoices
    ] + [
        PlatformOrganizationRecentDocument(
            type="quote",
            number=format_quote_number(q.quote_number),
            status=q.effective_status.value,
            total=q.total,
            currency_code=q.currency_code,
            created_at=q.created_at,
        )
        for q in recent_quotes
    ]
    recent_documents.sort(key=lambda d: d.created_at, reverse=True)
    recent_documents = recent_documents[:RECENT_DOCUMENTS_LIMIT]

    return PlatformOrganizationDetail(
        id=organization.id,
        name=organization.name,
        business_name=organization.business_name,
        status=OrganizationStatus(organization.status),
        owner_email=owner_email,
        members_count=members_count,
        invoices_count=invoices_count,
        quotes_count=quotes_count,
        customers_count=customers_count,
        products_count=products_count,
        language=organization.language,
        currency_code=organization.currency_code,
        timezone=organization.timezone,
        created_at=created_at,
        last_activity_at=last_activity_at,
        members=members,
        recent_documents=recent_documents,
    )


@router.get("/organizations/{organization_id}", response_model=PlatformOrganizationDetail)
def get_platform_organization(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformOrganizationDetail:
    require_platform_permission(current_user, PlatformPermission.organizations_view)
    organization = _organization_or_404(db, organization_id)
    return _build_organization_detail(db, organization)


@router.post("/organizations/{organization_id}/suspend", response_model=PlatformOrganizationDetail)
def suspend_platform_organization(
    organization_id: str,
    body: PlatformOrganizationActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformOrganizationDetail:
    require_platform_permission(current_user, PlatformPermission.organizations_manage)
    organization = _organization_or_404(db, organization_id)

    if organization.status == OrganizationStatus.suspended.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "organization_already_suspended",
                "message": "This organization is already suspended.",
            },
        )

    organization.status = OrganizationStatus.suspended.value
    record_organization_action(
        db,
        actor=current_user,
        action=PlatformAuditAction.organization_suspended,
        organization=organization,
        reason=body.reason,
        client_ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(organization)
    return _build_organization_detail(db, organization)


@router.post("/organizations/{organization_id}/reactivate", response_model=PlatformOrganizationDetail)
def reactivate_platform_organization(
    organization_id: str,
    body: PlatformOrganizationActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformOrganizationDetail:
    require_platform_permission(current_user, PlatformPermission.organizations_manage)
    organization = _organization_or_404(db, organization_id)

    if organization.status == OrganizationStatus.active.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "organization_already_active",
                "message": "This organization is already active.",
            },
        )

    organization.status = OrganizationStatus.active.value
    record_organization_action(
        db,
        actor=current_user,
        action=PlatformAuditAction.organization_reactivated,
        organization=organization,
        reason=body.reason,
        client_ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(organization)
    return _build_organization_detail(db, organization)


@router.get("/users", response_model=PaginatedPlatformUsersResponse)
def list_platform_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255),
    has_platform_role: bool | None = Query(default=None),
    email_verified: bool | None = Query(default=None),
) -> PaginatedPlatformUsersResponse:
    require_platform_permission(current_user, PlatformPermission.users_view)

    base_query = select(User)
    if search and search.strip():
        base_query = base_query.where(User.email.ilike(f"%{search.strip()}%"))
    if has_platform_role is not None:
        base_query = base_query.where(
            User.platform_role.isnot(None) if has_platform_role else User.platform_role.is_(None)
        )
    if email_verified is not None:
        base_query = base_query.where(
            User.email_verified_at.isnot(None) if email_verified else User.email_verified_at.is_(None)
        )

    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0

    users = db.scalars(base_query.order_by(User.email.asc()).limit(limit).offset(offset)).all()
    user_ids = [u.id for u in users]

    orgs_count_by_user = _organizations_count_by_user(db, user_ids)
    created_at_by_user = _user_created_at_map(db, user_ids)

    items = [
        PlatformUserSummary(
            id=u.id,
            email=u.email,
            email_verified=u.email_verified,
            status=UserStatus(u.status),
            platform_role=u.platform_role,
            organizations_count=orgs_count_by_user.get(u.id, 0),
            created_at=created_at_by_user.get(u.id),
        )
        for u in users
    ]
    return PaginatedPlatformUsersResponse(total=total, items=items)


def _user_or_404(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _count_active_super_admins(db: Session, *, exclude_user_id: str | None = None) -> int:
    """How many users currently hold platform_role=super_admin AND are
    status=active -- a disabled super_admin can't do anything anyway, so
    it never counts toward the "at least one active SUPER_ADMIN" safety
    margin required before disabling or revoking another one."""
    query = select(func.count()).select_from(User).where(
        User.platform_role == PlatformRole.super_admin.value,
        User.status == UserStatus.active.value,
    )
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    return db.scalar(query) or 0


def _build_user_detail(db: Session, user: User) -> PlatformUserDetail:
    """Shared by the plain GET detail endpoint and every user-management
    mutation below -- mirrors _build_organization_detail's exact
    rationale: mutations return this same shape directly, so the
    frontend never needs a second round-trip just to see its own
    result."""
    created_at = _user_created_at_map(db, [user.id]).get(user.id)

    membership_rows = db.execute(
        select(OrganizationMember, Organization.name)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(OrganizationMember.created_at.asc())
    ).all()
    organizations = [
        PlatformUserOrganization(
            organization_id=membership.organization_id,
            organization_name=org_name,
            role=membership.role,
            status=membership.status,
        )
        for membership, org_name in membership_rows
    ]

    return PlatformUserDetail(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified,
        status=UserStatus(user.status),
        platform_role=user.platform_role,
        created_at=created_at,
        organizations=organizations,
    )


@router.get("/users/{user_id}", response_model=PlatformUserDetail)
def get_platform_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformUserDetail:
    require_platform_permission(current_user, PlatformPermission.users_view)
    user = _user_or_404(db, user_id)
    return _build_user_detail(db, user)


@router.post("/users/{user_id}/disable", response_model=PlatformUserDetail)
def disable_platform_user(
    user_id: str,
    body: PlatformUserActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformUserDetail:
    require_platform_permission(current_user, PlatformPermission.users_manage)
    user = _user_or_404(db, user_id)

    if user.status == UserStatus.disabled.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "user_already_disabled", "message": "This user is already disabled."},
        )
    # Checked before the self-block below on purpose: when the target is
    # the sole active SUPER_ADMIN, that's true whether or not they're
    # also the actor (only a SUPER_ADMIN ever holds users_manage today),
    # so this is the more specific, more informative reason to surface --
    # "at least one admin must remain" explains the underlying invariant,
    # where a bare self-block would not.
    if user.platform_role == PlatformRole.super_admin.value and _count_active_super_admins(
        db, exclude_user_id=user.id
    ) < 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "cannot_disable_last_super_admin",
                "message": "At least one active SUPER_ADMIN must remain.",
            },
        )
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "cannot_disable_self",
                "message": "You cannot disable your own account through this endpoint.",
            },
        )

    user.status = UserStatus.disabled.value
    record_user_action(
        db,
        actor=current_user,
        action=PlatformAuditAction.user_disabled,
        target_user=user,
        reason=body.reason,
        client_ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return _build_user_detail(db, user)


@router.post("/users/{user_id}/enable", response_model=PlatformUserDetail)
def enable_platform_user(
    user_id: str,
    body: PlatformUserActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformUserDetail:
    require_platform_permission(current_user, PlatformPermission.users_manage)
    user = _user_or_404(db, user_id)

    if user.status == UserStatus.active.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "user_already_active", "message": "This user is already active."},
        )

    user.status = UserStatus.active.value
    record_user_action(
        db,
        actor=current_user,
        action=PlatformAuditAction.user_enabled,
        target_user=user,
        reason=body.reason,
        client_ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return _build_user_detail(db, user)


@router.post("/users/{user_id}/verify-email", response_model=PlatformUserDetail)
def force_verify_platform_user_email(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformUserDetail:
    # Directly marks the account verified -- unlike /auth/resend-verification,
    # this never sends another verification email or issues a token; force-
    # unverify does not exist (see this router's module docstring for the
    # scope this file deliberately stays within).
    require_platform_permission(current_user, PlatformPermission.users_manage)
    user = _user_or_404(db, user_id)

    if user.email_verified_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "already_verified", "message": "This user's email is already verified."},
        )

    user.email_verified_at = datetime.now(timezone.utc)
    record_user_action(
        db,
        actor=current_user,
        action=PlatformAuditAction.user_email_verified,
        target_user=user,
        reason="Force-verified by platform administrator",
        client_ip=get_client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return _build_user_detail(db, user)


@router.post("/users/{user_id}/send-password-reset", response_model=PlatformUserActionResponse)
def send_platform_user_password_reset(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformUserActionResponse:
    # Reuses app.routers.auth.issue_password_reset directly -- the exact
    # same token generation, prior-token invalidation, and email template
    # as the public forgot-password flow. The raw token never leaves that
    # function (it isn't returned here, logged, or included in the audit
    # row) -- an admin can trigger a reset email but never see or set the
    # password itself.
    #
    # Checked explicitly here, before calling issue_password_reset --
    # that function's own internal try/except around get_email_sender()
    # swallows an "emails disabled" failure exactly like it already
    # swallows "not configured" (correct for the anti-enumeration public
    # forgot-password flow), which would otherwise make this admin-facing
    # endpoint falsely claim success. The admin gets an honest 503
    # instead.
    require_platform_permission(current_user, PlatformPermission.users_manage)
    user = _user_or_404(db, user_id)

    if not get_effective_settings(db).emails_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "emails_disabled",
                "message": "Email sending is currently disabled by a platform administrator.",
            },
        )

    issue_password_reset(db, user)
    record_user_action(
        db,
        actor=current_user,
        action=PlatformAuditAction.user_password_reset_requested,
        target_user=user,
        reason="Password reset requested by platform administrator",
        client_ip=get_client_ip(request),
    )
    db.commit()
    return PlatformUserActionResponse(message=f"A password reset email has been sent to {user.email}.")


@router.post("/users/{user_id}/platform-role", response_model=PlatformUserDetail)
def set_platform_user_role(
    user_id: str,
    body: PlatformRoleActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformUserDetail:
    # Distinct permission from every other action on this page --
    # platform.roles.manage, not platform.users.manage -- granting/
    # revoking platform authority is a materially bigger consequential
    # action than disabling an account or resetting a password.
    require_platform_permission(current_user, PlatformPermission.roles_manage)
    user = _user_or_404(db, user_id)

    old_role = user.platform_role
    new_role = body.role.value if body.role is not None else None
    if old_role == new_role:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "platform_role_unchanged",
                "message": "This user already has that platform role.",
            },
        )
    # Checked before the self-block below, same reasoning as
    # disable_platform_user: when the target is the sole active
    # SUPER_ADMIN, that holds regardless of whether they're also the
    # actor, so this is the more specific of the two applicable reasons.
    if old_role == PlatformRole.super_admin.value and new_role != PlatformRole.super_admin.value:
        if _count_active_super_admins(db, exclude_user_id=user.id) < 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "cannot_revoke_last_super_admin",
                    "message": "At least one active SUPER_ADMIN must remain.",
                },
            )
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "cannot_modify_own_platform_role",
                "message": "You cannot change your own platform role through this endpoint.",
            },
        )

    user.platform_role = new_role
    action = (
        PlatformAuditAction.user_platform_role_granted
        if new_role is not None
        else PlatformAuditAction.user_platform_role_revoked
    )
    record_user_action(
        db,
        actor=current_user,
        action=action,
        target_user=user,
        reason=body.reason,
        client_ip=get_client_ip(request),
        details={"old_role": old_role, "new_role": new_role},
    )
    db.commit()
    db.refresh(user)
    return _build_user_detail(db, user)


@router.get("/system/health", response_model=PlatformSystemHealthResponse)
def get_platform_system_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformSystemHealthResponse:
    require_platform_permission(current_user, PlatformPermission.dashboard_view)
    return _system_health(db)


def _build_settings_response(db: Session, row: PlatformSettings) -> PlatformSettingsResponse:
    """Shared by the GET and PATCH handlers -- both need the exact same
    shape, and PATCH returns it directly so the frontend never needs a
    second round-trip just to see its own result (same convention as
    _build_organization_detail/_build_user_detail)."""
    ai_configured = is_ai_configured()
    _email_configured, email_provider = _email_provider_status()
    updated_by_email = (
        db.scalar(select(User.email).where(User.id == row.updated_by_user_id))
        if row.updated_by_user_id
        else None
    )

    return PlatformSettingsResponse(
        maintenance_mode=row.maintenance_mode,
        registrations_enabled=row.registrations_enabled,
        ai_enabled=row.ai_enabled,
        emails_enabled=row.emails_enabled,
        invoice_reminders_enabled=row.invoice_reminders_enabled,
        quote_reminders_enabled=row.quote_reminders_enabled,
        default_language=row.default_language,
        default_currency=row.default_currency,
        updated_at=row.updated_at,
        updated_by_email=updated_by_email,
        version=row.version,
        ai_provider=_ai_provider_name() if ai_configured else None,
        email_provider=email_provider,
        cors_allowed_origins=_cors_allowed_origins(),
    )


@router.get("/settings", response_model=PlatformSettingsResponse)
def get_platform_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformSettingsResponse:
    require_platform_permission(current_user, PlatformPermission.settings_view)
    row = get_or_create_settings_row(db)
    return _build_settings_response(db, row)


@router.patch("/settings", response_model=PlatformSettingsResponse)
def update_platform_settings(
    body: PlatformSettingsUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlatformSettingsResponse:
    """Optimistic-concurrency write: body.expected_version must match the
    row's current version, or this fails closed with 409 rather than
    silently overwriting a change another admin just made.

    The actual write is a single conditional
    `UPDATE ... WHERE id = :id AND version = :expected_version` (see the
    `update(PlatformSettings)` statement below), never ORM attribute
    mutation + a blind commit -- that would race two concurrent PATCHes
    exactly like it used to. Whichever request's UPDATE statement runs
    first (Postgres row lock or SQLite's single-writer serialization, it
    doesn't matter which) commits and bumps the version; a second,
    concurrent request's UPDATE then evaluates `version = :expected_version`
    against the now-current row and matches zero rows -- `result.rowcount
    == 0` is the engine-agnostic conflict signal this endpoint relies on,
    not anything computed in Python beforehand. The diff read below is
    only used to build the audit details and short-circuit a true no-op;
    it plays no role in concurrency safety.
    """
    require_platform_permission(current_user, PlatformPermission.settings_manage)
    row = get_or_create_settings_row(db)

    # Diff only the fields the caller actually supplied -- reject-empty
    # is already enforced at the schema layer (PlatformSettingsUpdateRequest
    # requires at least one), but a request that supplies fields whose
    # values all already match the current row is a no-op, not a "change,"
    # and must not write an audit row either.
    provided = body.model_dump(exclude_unset=True, exclude={"reason", "expected_version"}, mode="json")
    changes: dict[str, dict[str, object]] = {}
    for field, new_value in provided.items():
        old_value = getattr(row, field)
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}

    if not changes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "no_changes",
                "message": "The provided values already match the current settings.",
            },
        )

    new_version = body.expected_version + 1
    result = db.execute(
        update(PlatformSettings)
        .where(
            PlatformSettings.id == PLATFORM_SETTINGS_SINGLETON_ID,
            PlatformSettings.version == body.expected_version,
        )
        .values(
            **{field: provided[field] for field in changes},
            version=new_version,
            updated_by_user_id=current_user.id,
        )
    )
    if result.rowcount == 0:
        db.rollback()
        current_version = db.scalar(
            select(PlatformSettings.version).where(PlatformSettings.id == PLATFORM_SETTINGS_SINGLETON_ID)
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "platform_settings_version_conflict",
                "message": "These settings were changed by another administrator. Reload and try again.",
                "current_version": current_version,
            },
        )

    record_settings_action(
        db,
        actor=current_user,
        reason=body.reason,
        client_ip=get_client_ip(request),
        details={"old_version": body.expected_version, "new_version": new_version, **changes},
    )
    db.commit()
    db.refresh(row)
    return _build_settings_response(db, row)


def _audit_log_entry(row: PlatformAuditLog) -> PlatformAuditLogEntry:
    """Builds the sanitized response shape from a raw row -- the only
    place `details`/`client_ip` are ever read back out of the database
    for rendering, so this is the one required chokepoint for
    sanitize_audit_details/mask_client_ip; no other code path may read
    those two columns and hand them to a caller unsanitized."""
    target_type: str | None = None
    if row.target_organization_id is not None:
        target_type = "organization"
    elif row.target_user_id is not None:
        target_type = "user"

    return PlatformAuditLogEntry(
        id=row.id,
        action=row.action,
        actor_user_id=row.actor_user_id,
        actor_email=row.actor_email,
        target_type=target_type,
        target_organization_id=row.target_organization_id,
        target_organization_name=row.target_organization_name or None,
        target_user_id=row.target_user_id,
        target_user_email=row.target_user_email,
        reason=row.reason,
        details=sanitize_audit_details(row.details),
        client_ip=mask_client_ip(row.client_ip),
        created_at=row.created_at,
    )


@router.get("/audit-log", response_model=PaginatedPlatformAuditLogResponse)
def list_platform_audit_log(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    actor_user_id: str | None = Query(default=None),
    actor_email: str | None = Query(default=None, max_length=255),
    target_organization_id: str | None = Query(default=None),
    target_user_id: str | None = Query(default=None),
    target_search: str | None = Query(
        default=None,
        max_length=255,
        description="Substring match against the target organization name or target user email snapshot.",
    ),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> PaginatedPlatformAuditLogResponse:
    require_platform_permission(current_user, PlatformPermission.audit_view)

    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_date_range", "message": "date_from must not be after date_to."},
        )

    # Reads the append-only table directly, never joined against the
    # live Organization/User tables -- every displayable field is
    # already a snapshot on the row itself (see PlatformAuditLog's own
    # docstring), so history stays accurate and queryable even after the
    # live org/user it refers to is renamed or deleted.
    base_query = select(PlatformAuditLog)
    if action:
        base_query = base_query.where(PlatformAuditLog.action == action)
    if actor_user_id:
        base_query = base_query.where(PlatformAuditLog.actor_user_id == actor_user_id)
    if actor_email and actor_email.strip():
        base_query = base_query.where(PlatformAuditLog.actor_email.ilike(f"%{actor_email.strip()}%"))
    if target_organization_id:
        base_query = base_query.where(PlatformAuditLog.target_organization_id == target_organization_id)
    if target_user_id:
        base_query = base_query.where(PlatformAuditLog.target_user_id == target_user_id)
    if target_search and target_search.strip():
        term = f"%{target_search.strip()}%"
        base_query = base_query.where(
            or_(
                PlatformAuditLog.target_organization_name.ilike(term),
                PlatformAuditLog.target_user_email.ilike(term),
            )
        )
    if date_from is not None:
        base_query = base_query.where(PlatformAuditLog.created_at >= date_from)
    if date_to is not None:
        # Inclusive of the entire end date, not just its midnight instant.
        base_query = base_query.where(PlatformAuditLog.created_at < date_to + timedelta(days=1))

    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0

    rows = db.scalars(
        base_query.order_by(PlatformAuditLog.created_at.desc(), PlatformAuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return PaginatedPlatformAuditLogResponse(
        total=total, items=[_audit_log_entry(row) for row in rows]
    )
