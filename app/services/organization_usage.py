"""The single centralized place that measures how much of each
plan-limited resource an organization is currently using.

Phase 14B measures usage only -- it deliberately does not reject any
request because of a limit (that is Phase 14C's job, once this module's
numbers are trusted). No router computes a count itself; every consumer
calls get_usage_snapshot(), which is the only function that combines a
count with its matching entitlement limit (see app.services.entitlements,
the sole source of limits -- this module is the sole source of usage).

Every count here is calculated live from authoritative tables at read
time: there is no background job, no cached counter column, and nothing
written anywhere as a side effect of reading usage (no audit row either
-- a read is not a mutation).

Users/customers/products are standing counts (how many exist right now).
Invoices/quotes/AI actions are monthly-creation counts (how many were
created since the start of the current UTC calendar month -- the same
"this month" convention app.routers.dashboard._month_bounds already
established for revenue, not a second, divergent definition of it).
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.membership_status import MembershipStatus
from app.models import AssistantAction, Customer, Invoice, OrganizationMember, Product, Quote
from app.services.entitlements import Entitlements, PlanLimit, get_limit, get_organization_entitlements


@dataclass(frozen=True)
class ResourceUsage:
    """used/limit/unlimited for exactly one plan-limited resource -- the
    frontend renders these directly (e.g. "18 / 50") without the backend
    ever computing a percentage or a warning threshold itself."""

    used: int
    limit: int | None
    unlimited: bool


@dataclass(frozen=True)
class UsageSnapshot:
    users: ResourceUsage
    customers: ResourceUsage
    products: ResourceUsage
    invoices: ResourceUsage
    quotes: ResourceUsage
    ai_actions: ResourceUsage
    storage: ResourceUsage


def _current_month_start_utc(now: datetime | None = None) -> datetime:
    """UTC-aware start of the current calendar month -- matches
    app.routers.dashboard._month_bounds's own convention exactly, so
    "this month" means the same thing everywhere in this app rather than
    introducing a second, org-timezone-aware definition that would
    quietly disagree with the dashboard's revenue-this-month figure."""
    moment = now or datetime.now(timezone.utc)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def count_users(db: Session, organization_id: str) -> int:
    """Active memberships only -- matches the existing
    app.routers.platform_admin._active_member_count_by_org convention.
    A pending invitation or a removed member never counts against the
    seat limit."""
    return (
        db.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.status == MembershipStatus.active.value,
            )
        )
        or 0
    )


def count_customers(db: Session, organization_id: str) -> int:
    """A plain row count -- Customer has no soft-delete flag at all
    (DELETE is a genuine hard delete), so every row that still exists is
    live by definition."""
    return (
        db.scalar(select(func.count()).select_from(Customer).where(Customer.organization_id == organization_id))
        or 0
    )


def count_products(db: Session, organization_id: str) -> int:
    """Active (non-archived) products only. Archiving a product is the
    only "removal" mechanism this app has (see Product's own docstring
    on why there is no delete endpoint) -- an archived product no longer
    counts against the catalog-size limit, and restoring it counts
    again, exactly like a standing inventory should behave."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.organization_id == organization_id, Product.active.is_(True))
        )
        or 0
    )


def count_invoices_current_month(db: Session, organization_id: str, *, now: datetime | None = None) -> int:
    """Invoices are never deleted (no DELETE endpoint exists), so this is
    simply every invoice created since the start of the current UTC
    calendar month."""
    month_start = _current_month_start_utc(now)
    return (
        db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.organization_id == organization_id, Invoice.created_at >= month_start)
        )
        or 0
    )


def count_quotes_current_month(db: Session, organization_id: str, *, now: datetime | None = None) -> int:
    """Every quote created this month counts toward the monthly quota
    regardless of its current active/archived flag -- archiving a quote
    after creation doesn't undo the fact that it consumed this month's
    allowance. Only a genuine hard delete removes a quote from this
    count, and that path only ever exists for drafts (see
    app.services.quotes.delete_draft_quote_record) -- a quote created and
    immediately discarded the same month correctly stops counting,
    since the row is simply gone from the authoritative table."""
    month_start = _current_month_start_utc(now)
    return (
        db.scalar(
            select(func.count())
            .select_from(Quote)
            .where(Quote.organization_id == organization_id, Quote.created_at >= month_start)
        )
        or 0
    )


def count_ai_actions_current_month(db: Session, organization_id: str, *, now: datetime | None = None) -> int:
    """Counts AssistantAction rows (see that model's own docstring) --
    the only persisted, authoritative record of an AI action in this
    codebase today. Counts every status (proposed/executed/cancelled/
    expired/failed): the model call already happened the moment a row
    was created, regardless of whether a human later confirmed it.
    Plain conversational chat turns that never invoke a tool are not
    logged anywhere in this app and so cannot be counted here -- a
    documented limitation, not a silent gap."""
    month_start = _current_month_start_utc(now)
    return (
        db.scalar(
            select(func.count())
            .select_from(AssistantAction)
            .where(AssistantAction.organization_id == organization_id, AssistantAction.created_at >= month_start)
        )
        or 0
    )


def count_storage(db: Session, organization_id: str) -> int:
    """Always 0 -- this app has no file-upload/storage subsystem at all
    today (logo_url is a plain external URL string, never an uploaded
    file; see the Phase 14B audit). Returning 0 is the honest current
    state of the world, not a placeholder standing in for real data --
    revisit this the moment a real storage feature is introduced."""
    return 0


def _resource_usage(used: int, limit: int | None) -> ResourceUsage:
    return ResourceUsage(used=used, limit=limit, unlimited=limit is None)


def get_usage_snapshot(db: Session, organization_id: str) -> UsageSnapshot:
    """The one function every consumer (the tenant-facing usage endpoint,
    the platform admin organization detail response) should call. Combines
    this module's live counts with app.services.entitlements' limits --
    nothing outside these two modules ever computes usage or reads a
    Plan/limit column directly."""
    entitlements: Entitlements = get_organization_entitlements(db, organization_id)

    return UsageSnapshot(
        users=_resource_usage(count_users(db, organization_id), get_limit(entitlements, PlanLimit.max_users)),
        customers=_resource_usage(
            count_customers(db, organization_id), get_limit(entitlements, PlanLimit.max_customers)
        ),
        products=_resource_usage(
            count_products(db, organization_id), get_limit(entitlements, PlanLimit.max_products)
        ),
        invoices=_resource_usage(
            count_invoices_current_month(db, organization_id),
            get_limit(entitlements, PlanLimit.max_invoices_per_month),
        ),
        quotes=_resource_usage(
            count_quotes_current_month(db, organization_id),
            get_limit(entitlements, PlanLimit.max_quotes_per_month),
        ),
        ai_actions=_resource_usage(
            count_ai_actions_current_month(db, organization_id),
            get_limit(entitlements, PlanLimit.max_ai_actions_per_month),
        ),
        storage=_resource_usage(
            count_storage(db, organization_id), get_limit(entitlements, PlanLimit.storage_limit_mb)
        ),
    )
