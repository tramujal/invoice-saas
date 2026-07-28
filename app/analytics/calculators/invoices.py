"""Invoice-count and invoice-value calculators -- tenant-scoped, window-
aware, and independently testable in isolation from AnalyticsService.

Every count here uses each invoice's EFFECTIVE payment status (due-date-
derived, via app.effective_status), never the raw stored payment_status
column -- the analytics layer must agree with every other surface (PDF,
email, dashboard, insights, assistant) on what's actually overdue. This
was previously a private helper (_effective_status_counts) inside
app.routers.dashboard; it lives here now as the one implementation every
caller (the dashboard router, the insights engine, the new analytics
endpoint) shares.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.primitives import quantize_money
from app.analytics.time_windows import TimeWindow
from app.effective_status import get_effective_payment_status
from app.models import Invoice, Organization
from app.org_time import get_organization_today
from app.payment_status import PaymentStatus


@dataclass(frozen=True)
class InvoiceCounts:
    total: int
    pending: int
    paid: int
    overdue: int


def get_invoice_counts(
    db: Session, organization_id: str, *, window: TimeWindow | None = None
) -> InvoiceCounts:
    """Invoice counts by effective payment status. `window`, when given,
    filters on Invoice.created_at -- every invoice CREATED in that
    window, regardless of when it later became overdue or was paid
    (matching every other "in this window" calculator in this package)."""
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)

    query = select(Invoice.payment_status, Invoice.due_date).where(
        Invoice.organization_id == organization_id
    )
    if window is not None:
        query = query.where(Invoice.created_at >= window.start, Invoice.created_at < window.end)

    rows = db.execute(query).all()
    counts: dict[str, int] = {}
    for row in rows:
        effective = get_effective_payment_status(row, today_local)
        counts[effective.value] = counts.get(effective.value, 0) + 1

    return InvoiceCounts(
        total=len(rows),
        pending=counts.get(PaymentStatus.pending.value, 0),
        paid=counts.get(PaymentStatus.paid.value, 0),
        overdue=counts.get(PaymentStatus.overdue.value, 0),
    )


def get_average_invoice_value(
    db: Session, organization_id: str, *, window: TimeWindow | None = None
) -> dict[str, Decimal]:
    """{currency_code: average invoice total}, one entry per currency with
    at least one invoice in scope -- never averaged across currencies,
    the same rule every revenue figure in this app already follows.
    Computed with SQL avg(), not a Python mean over fetched rows, per this
    phase's "aggregate inside SQL whenever practical" goal."""
    query = select(Invoice.currency_code, func.avg(Invoice.total)).where(
        Invoice.organization_id == organization_id
    )
    if window is not None:
        query = query.where(Invoice.created_at >= window.start, Invoice.created_at < window.end)
    query = query.group_by(Invoice.currency_code)

    rows = db.execute(query).all()
    # str(avg) before Decimal(): SQLite's avg() returns a plain float, and
    # Decimal(float) reproduces the float's own binary-rounding noise
    # (e.g. Decimal(0.1) has 50+ spurious digits) -- routing through str()
    # first avoids that regardless of which backend produced the value.
    return {
        code: quantize_money(Decimal(str(avg))) for code, avg in rows if avg is not None
    }


def get_pending_by_currency(db: Session, organization_id: str) -> dict[str, Decimal]:
    """{currency_code: total of invoices whose STORED payment_status is
    literally "pending"} -- deliberately the raw column, not the
    effective status get_invoice_counts/get_revenue_breakdown use
    elsewhere in this module. This preserves the exact original behavior
    of app.routers.dashboard.get_pending_total_by_currency (relocated
    here verbatim), which app.insights.engine's cash-flow-exposure insight
    depends on: an invoice whose due date has quietly passed but whose
    payment_status was never explicitly updated is still counted as
    "pending money still on the books" here, not silently reclassified
    into "overdue" the way it would be if this used the effective-status
    helper instead. Changing that classification is a real product
    decision, not something this phase's refactor should do as a side
    effect -- see this phase's own completion report for the tradeoff."""
    rows = dict(
        db.execute(
            select(Invoice.currency_code, func.coalesce(func.sum(Invoice.total), 0))
            .where(
                Invoice.organization_id == organization_id,
                Invoice.payment_status == PaymentStatus.pending.value,
            )
            .group_by(Invoice.currency_code)
        ).all()
    )
    return {code: quantize_money(total) for code, total in rows.items()}


def get_monthly_invoice_counts(
    db: Session, organization_id: str, month_starts: list[datetime]
) -> list[tuple[str, int]]:
    """Invoice-count trend, one (month, count) point per month in
    `month_starts` (oldest first) -- currency-agnostic (a count, not
    money, so combining it across currencies is fine, matching every
    other plain invoice count in this app). Bucketed in Python from a
    single bounded query: SQLite and Postgres don't share a portable
    "truncate to month" function, and at this app's scale (one org's
    invoices over a handful of months) fetching the bounded row set and
    summing here is simple and correct on both backends -- the same
    reasoning app.quote_analytics.get_quote_monthly_conversions already
    documents for its own identical bucketing."""
    range_start = month_starts[0]
    rows = db.execute(
        select(Invoice.created_at).where(
            Invoice.organization_id == organization_id, Invoice.created_at >= range_start
        )
    ).all()

    counts: dict[str, int] = {start.strftime("%Y-%m"): 0 for start in month_starts}
    for (created_at,) in rows:
        key = created_at.strftime("%Y-%m")
        if key in counts:
            counts[key] += 1
    return [(key, counts[key]) for key in sorted(counts)]
