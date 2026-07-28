"""Customer-facing calculators: growth, retention, and top customers by
revenue.

Growth and retention are genuinely new metrics -- nothing in this
codebase computed either before this phase. Top customers is relocated
(not duplicated) from app.routers.dashboard.get_dashboard_analytics_data,
which used to compute it as a byproduct of building the entire dashboard
payload; it's callable on its own now.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.primitives import quantize_money
from app.analytics.time_windows import TimeWindow
from app.models import Customer, Invoice


def get_customer_growth(db: Session, organization_id: str, *, window: TimeWindow) -> int:
    """Count of customers CREATED within `window` -- the simplest possible
    growth signal. Deriving a percentage on top of this is left to the
    caller: it needs a second window's count, the same composition
    get_revenue_growth uses (two calls to get_revenue_by_currency) rather
    than this function taking two windows itself."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Customer)
            .where(
                Customer.organization_id == organization_id,
                Customer.created_at >= window.start,
                Customer.created_at < window.end,
            )
        )
        or 0
    )


@dataclass(frozen=True)
class RetentionRate:
    total_invoiced_customers: int
    repeat_customers: int  # customers with 2+ invoices, all-time
    retention_rate_percent: float | None


def get_customer_retention(db: Session, organization_id: str) -> RetentionRate:
    """All-time, deliberately not windowed: "of everyone we've ever
    invoiced, what share came back for a second invoice" is a lifetime
    relationship metric -- a customer's first and second invoice can fall
    in different windows, so slicing this to e.g. a rolling 30-day window
    would silently undercount every genuine repeat customer whose second
    purchase happened to land outside it. A windowed variant is a natural
    future extension once a concrete use case needs one, not added
    speculatively here (see this phase's own completion report)."""
    rows = db.execute(
        select(Invoice.customer_id, func.count(Invoice.id))
        .where(
            Invoice.organization_id == organization_id,
            Invoice.customer_id.is_not(None),
        )
        .group_by(Invoice.customer_id)
    ).all()

    total = len(rows)
    repeat = sum(1 for _customer_id, count in rows if count >= 2)
    rate = (repeat / total * 100) if total > 0 else None
    return RetentionRate(
        total_invoiced_customers=total, repeat_customers=repeat, retention_rate_percent=rate
    )


@dataclass(frozen=True)
class TopCustomer:
    customer_id: str
    customer_name: str
    currency_code: str
    revenue: Decimal


def get_top_customers(
    db: Session, organization_id: str, *, limit: int = 5, window: TimeWindow | None = None
) -> list[TopCustomer]:
    """Top customers by revenue, ranked independently within each
    currency -- relocated from
    app.routers.dashboard.get_dashboard_analytics_data (identical query,
    identical ranked-in-Python-not-a-SQL-window-function approach, per
    that function's own rationale: simple, portable queries over
    backend-specific SQL)."""
    query = (
        select(
            Customer.id,
            Customer.name,
            Invoice.currency_code,
            func.sum(Invoice.total).label("revenue"),
        )
        .join(Invoice, Invoice.customer_id == Customer.id)
        .where(Invoice.organization_id == organization_id)
    )
    if window is not None:
        query = query.where(Invoice.created_at >= window.start, Invoice.created_at < window.end)
    query = query.group_by(Customer.id, Customer.name, Invoice.currency_code)

    rows_by_currency: dict[str, list] = {}
    for row in db.execute(query).all():
        rows_by_currency.setdefault(row.currency_code, []).append(row)

    top: list[TopCustomer] = []
    for currency_code in sorted(rows_by_currency):
        ranked = sorted(rows_by_currency[currency_code], key=lambda r: r.revenue, reverse=True)
        for row in ranked[:limit]:
            top.append(
                TopCustomer(
                    customer_id=row.id,
                    customer_name=row.name,
                    currency_code=currency_code,
                    revenue=quantize_money(row.revenue),
                )
            )
    return top
