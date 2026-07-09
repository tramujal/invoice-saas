from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_org_member
from app.models import Customer, Invoice, User
from app.payment_status import PaymentStatus
from app.schemas import (
    DashboardAnalyticsResponse,
    DashboardResponse,
    MonthlySummaryPoint,
    PaymentStatusCountPoint,
    TopCustomerRevenue,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/dashboard", tags=["dashboard"]
)

RECENT_INVOICES_LIMIT = 5
MONTHLY_SUMMARY_MONTHS = 6
TOP_CUSTOMERS_LIMIT = 5


def _quantize_money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def _month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Returns (start of last month, start of this month), both UTC-aware.

    Kept timezone-aware (rather than stripped to naive) so comparisons against
    Invoice.created_at are unambiguous on Postgres, where DateTime(timezone=True)
    columns are genuinely tz-aware; SQLite ignores tzinfo harmlessly either way.
    """
    this_month_start = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if this_month_start.month == 1:
        last_month_start = this_month_start.replace(
            year=this_month_start.year - 1, month=12
        )
    else:
        last_month_start = this_month_start.replace(
            month=this_month_start.month - 1
        )
    return last_month_start, this_month_start


def _last_n_month_starts(now: datetime, n: int) -> list[datetime]:
    """Returns n consecutive month-start datetimes (UTC-aware), oldest
    first, ending with the current month."""
    year, month = now.year, now.month
    starts: list[datetime] = []
    for _ in range(n):
        starts.append(datetime(year, month, 1, tzinfo=timezone.utc))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(starts))


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    require_org_member(current_user, organization_id, db)

    org_filter = Invoice.organization_id == organization_id

    total_invoices = (
        db.scalar(select(func.count()).select_from(Invoice).where(org_filter)) or 0
    )
    total_customers = (
        db.scalar(
            select(func.count())
            .select_from(Customer)
            .where(Customer.organization_id == organization_id)
        )
        or 0
    )
    total_revenue = _quantize_money(
        db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(org_filter))
        or Decimal("0")
    )

    status_counts = dict(
        db.execute(
            select(Invoice.payment_status, func.count())
            .where(org_filter)
            .group_by(Invoice.payment_status)
        ).all()
    )

    last_month_start, this_month_start = _month_bounds(datetime.now(timezone.utc))

    revenue_this_month = _quantize_money(
        db.scalar(
            select(func.coalesce(func.sum(Invoice.total), 0)).where(
                org_filter, Invoice.created_at >= this_month_start
            )
        )
        or Decimal("0")
    )
    revenue_last_month = _quantize_money(
        db.scalar(
            select(func.coalesce(func.sum(Invoice.total), 0)).where(
                org_filter,
                Invoice.created_at >= last_month_start,
                Invoice.created_at < this_month_start,
            )
        )
        or Decimal("0")
    )

    revenue_growth_percent: Decimal | None = None
    if revenue_last_month > 0:
        revenue_growth_percent = (
            (revenue_this_month - revenue_last_month) / revenue_last_month * 100
        ).quantize(Decimal("0.01"))

    recent_invoices = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(org_filter)
        .order_by(Invoice.created_at.desc())
        .limit(RECENT_INVOICES_LIMIT)
    ).all()

    return DashboardResponse(
        total_revenue=total_revenue,
        total_invoices=total_invoices,
        total_customers=total_customers,
        pending_invoices=status_counts.get(PaymentStatus.pending.value, 0),
        paid_invoices=status_counts.get(PaymentStatus.paid.value, 0),
        overdue_invoices=status_counts.get(PaymentStatus.overdue.value, 0),
        revenue_this_month=revenue_this_month,
        revenue_last_month=revenue_last_month,
        revenue_growth_percent=revenue_growth_percent,
        recent_invoices=list(recent_invoices),
    )


@router.get("/analytics", response_model=DashboardAnalyticsResponse)
def get_dashboard_analytics(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardAnalyticsResponse:
    require_org_member(current_user, organization_id, db)

    org_filter = Invoice.organization_id == organization_id

    # --- monthly revenue + invoice count, last N months ---
    # Bucketed in Python rather than SQL GROUP BY month: SQLite and Postgres
    # don't share a portable "truncate to month" function, and at this app's
    # scale (one org's invoices over a few months) fetching the bounded row
    # set and summing here is simple and correct on both backends.
    month_starts = _last_n_month_starts(datetime.now(timezone.utc), MONTHLY_SUMMARY_MONTHS)
    range_start = month_starts[0]

    rows = db.execute(
        select(Invoice.created_at, Invoice.total).where(
            org_filter, Invoice.created_at >= range_start
        )
    ).all()

    buckets: dict[str, dict[str, Decimal | int]] = {
        _month_key(start): {"revenue": Decimal("0"), "invoice_count": 0}
        for start in month_starts
    }
    for created_at, total in rows:
        key = _month_key(created_at)
        bucket = buckets.get(key)
        if bucket is not None:
            bucket["revenue"] += total
            bucket["invoice_count"] += 1

    monthly_summary = [
        MonthlySummaryPoint(
            month=key,
            revenue=_quantize_money(buckets[key]["revenue"]),
            invoice_count=buckets[key]["invoice_count"],
        )
        for key in sorted(buckets)
    ]

    # --- invoice count by payment status, all-time ---
    status_counts = dict(
        db.execute(
            select(Invoice.payment_status, func.count())
            .where(org_filter)
            .group_by(Invoice.payment_status)
        ).all()
    )
    invoice_count_by_status = [
        PaymentStatusCountPoint(
            status=status, count=status_counts.get(status.value, 0)
        )
        for status in PaymentStatus
    ]

    # --- top customers by revenue, all-time ---
    top_customer_rows = db.execute(
        select(
            Customer.id, Customer.name, func.sum(Invoice.total).label("revenue")
        )
        .join(Invoice, Invoice.customer_id == Customer.id)
        .where(Invoice.organization_id == organization_id)
        .group_by(Customer.id, Customer.name)
        .order_by(func.sum(Invoice.total).desc())
        .limit(TOP_CUSTOMERS_LIMIT)
    ).all()
    top_customers = [
        TopCustomerRevenue(
            customer_id=row.id,
            customer_name=row.name,
            revenue=_quantize_money(row.revenue),
        )
        for row in top_customer_rows
    ]

    return DashboardAnalyticsResponse(
        monthly_summary=monthly_summary,
        invoice_count_by_status=invoice_count_by_status,
        top_customers=top_customers,
    )
