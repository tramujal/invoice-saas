from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_org_member
from app.models import Customer, Invoice, User
from app.payment_status import PaymentStatus
from app.schemas import DashboardResponse

router = APIRouter(
    prefix="/organizations/{organization_id}/dashboard", tags=["dashboard"]
)

RECENT_INVOICES_LIMIT = 5


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
