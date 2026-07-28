"""Revenue calculators -- every "how much money" metric this app computes,
in one place. All grouped by currency_code and never summed across
currencies (a "$100 + UYU 1000" total is meaningless) -- the same rule
app.routers.dashboard's original revenue figures already followed.

"Revenue" means booked/invoiced (Invoice.total), not collected -- matching
every existing revenue figure in this app (see app.product_analytics's own
note on this exact convention). Paid/outstanding/overdue split that same
booked total by effective payment status; they are not a second, different
notion of revenue.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.primitives import growth_percent, quantize_money
from app.analytics.time_windows import TimeWindow
from app.effective_status import get_effective_payment_status
from app.models import Invoice, Organization
from app.org_time import get_organization_today
from app.payment_status import PaymentStatus


def get_revenue_by_currency(
    db: Session, organization_id: str, *, window: TimeWindow | None = None
) -> dict[str, Decimal]:
    """Total booked revenue per currency -- the base figure
    get_revenue_growth below derives from by calling this twice (once per
    window) rather than duplicating the query."""
    query = select(Invoice.currency_code, func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.organization_id == organization_id
    )
    if window is not None:
        query = query.where(Invoice.created_at >= window.start, Invoice.created_at < window.end)
    query = query.group_by(Invoice.currency_code)

    rows = db.execute(query).all()
    return {code: quantize_money(Decimal(total)) for code, total in rows}


@dataclass(frozen=True)
class RevenueBreakdown:
    """One currency's revenue, split by EFFECTIVE payment status -- `paid`
    + `outstanding` always sums back to `total` (outstanding means
    "pending or overdue," not a third, overlapping bucket)."""

    currency_code: str
    total: Decimal
    paid: Decimal
    outstanding: Decimal
    overdue: Decimal


def get_revenue_breakdown(
    db: Session, organization_id: str, *, window: TimeWindow | None = None
) -> list[RevenueBreakdown]:
    """Paid / outstanding / overdue revenue per currency, from a single
    query -- never three separate sums, since every invoice's effective
    status has to be derived in Python anyway (see app.effective_status)
    and the same fetched rows already carry currency_code and total."""
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)

    query = select(
        Invoice.currency_code, Invoice.total, Invoice.payment_status, Invoice.due_date
    ).where(Invoice.organization_id == organization_id)
    if window is not None:
        query = query.where(Invoice.created_at >= window.start, Invoice.created_at < window.end)

    totals: dict[str, dict[str, Decimal]] = {}
    for row in db.execute(query).all():
        bucket = totals.setdefault(
            row.currency_code,
            {"total": Decimal("0"), "paid": Decimal("0"), "overdue": Decimal("0")},
        )
        bucket["total"] += row.total
        effective = get_effective_payment_status(row, today_local)
        if effective == PaymentStatus.paid:
            bucket["paid"] += row.total
        elif effective == PaymentStatus.overdue:
            bucket["overdue"] += row.total

    return [
        RevenueBreakdown(
            currency_code=code,
            total=quantize_money(values["total"]),
            paid=quantize_money(values["paid"]),
            outstanding=quantize_money(values["total"] - values["paid"]),
            overdue=quantize_money(values["overdue"]),
        )
        for code, values in sorted(totals.items())
    ]


def get_revenue_growth(
    db: Session, organization_id: str, *, current: TimeWindow, previous: TimeWindow
) -> dict[str, Decimal | None]:
    """{currency_code: growth percent, current window vs. previous window}
    -- built on app.analytics.primitives.growth_percent, the one
    canonical growth formula, applied per currency. A currency present in
    `current` but absent from `previous` returns None (no baseline),
    matching every other "first period" case in this app rather than
    reporting a misleading infinite percentage."""
    current_totals = get_revenue_by_currency(db, organization_id, window=current)
    previous_totals = get_revenue_by_currency(db, organization_id, window=previous)
    codes = set(current_totals) | set(previous_totals)
    return {
        code: growth_percent(
            current_totals.get(code, Decimal("0")), previous_totals.get(code, Decimal("0"))
        )
        for code in codes
    }


def get_monthly_revenue_series(
    db: Session, organization_id: str, month_starts: list[datetime]
) -> list[tuple[str, str, Decimal]]:
    """Revenue trend, one (month, currency_code, revenue) point per month
    in `month_starts` (oldest first) x every currency seen anywhere in
    the window -- zero-filled so each currency gets a full, contiguous
    series instead of gaps on months where it happened to have no
    invoices. Bucketed in Python from one bounded query, matching
    app.analytics.calculators.invoices.get_monthly_invoice_counts's
    identical rationale (no portable cross-backend "truncate to month")."""
    range_start = month_starts[0]
    rows = db.execute(
        select(Invoice.created_at, Invoice.total, Invoice.currency_code).where(
            Invoice.organization_id == organization_id, Invoice.created_at >= range_start
        )
    ).all()

    currencies_seen = {currency_code for _, _, currency_code in rows}
    buckets: dict[tuple[str, str], Decimal] = {
        (start.strftime("%Y-%m"), currency_code): Decimal("0")
        for start in month_starts
        for currency_code in currencies_seen
    }
    for created_at, total, currency_code in rows:
        key = (created_at.strftime("%Y-%m"), currency_code)
        if key in buckets:
            buckets[key] += total

    return [
        (month, currency_code, quantize_money(revenue))
        for (month, currency_code), revenue in sorted(buckets.items())
    ]
