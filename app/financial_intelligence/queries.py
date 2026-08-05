"""Bounded, org-scoped SQL queries genuinely new to the Financial
Intelligence module -- everything app.analytics.service.AnalyticsService
(or app.product_analytics / app.quote_analytics) already computes is
called from there directly; nothing here duplicates it.

Every function takes organization_id explicitly and filters on it, issues
a single query (never a Python loop issuing one query per row), and
accepts `today`/`now`/`month_starts` as explicit parameters rather than
reading the clock itself -- callers (metrics.py, cashflow.py, tests) pin
these deterministically, matching app.analytics.time_windows' own
discipline.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer, Invoice, InvoiceLineItem, Product, Quote
from app.payment_status import PaymentStatus
from app.quote_status import QuoteStatus

# Same defensive ceiling app/insights/queries.py already uses for its own
# bounded detail queries -- a real SMB organization is very unlikely to
# have more open/overdue invoices than this at once; this bounds the
# query even in a pathological case rather than fetching an unbounded set.
OPEN_INVOICE_DETAIL_LIMIT = 2000


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for DateTime(timezone=True)
    columns (Postgres returns aware ones) -- normalize once, matching
    app/insights/queries.py's identical note."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class OpenInvoiceRow:
    """One unpaid invoice, with just the fields the aging/collections-
    calendar/concentration calculations need -- never the full ORM
    object, so callers can't accidentally reach for a field this query
    didn't intend to expose (e.g. customer PII beyond name/id)."""

    invoice_id: str
    invoice_number: int
    customer_id: str | None
    customer_name: str | None
    currency_code: str
    total: Decimal
    due_date: date | None
    created_at: datetime


def get_open_invoices(db: Session, organization_id: str) -> list[OpenInvoiceRow]:
    """Every invoice whose STORED payment_status is not "paid" -- the
    base row set for AR aging, the collections calendar, and top-overdue-
    customers, all of which need to further classify these into not-yet-
    due/overdue-by-N-days themselves (using an explicitly-passed
    `today_local`, never recomputed here) rather than this query taking a
    stance on "overdue" itself."""
    rows = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(
            Invoice.organization_id == organization_id,
            Invoice.payment_status != PaymentStatus.paid.value,
        )
        .order_by(Invoice.due_date.asc().nulls_last(), Invoice.created_at.asc())
        .limit(OPEN_INVOICE_DETAIL_LIMIT)
    ).all()
    return [
        OpenInvoiceRow(
            invoice_id=inv.id,
            invoice_number=inv.invoice_number,
            customer_id=inv.customer_id,
            customer_name=inv.customer_name,
            currency_code=inv.currency_code,
            total=inv.total,
            due_date=inv.due_date,
            created_at=_aware(inv.created_at),
        )
        for inv in rows
    ]


@dataclass(frozen=True)
class CustomerRevenueRow:
    """One customer's all-time revenue + invoice count in one currency --
    the base row set for concentration, repeat-customer contribution, and
    (paired with get_open_invoices) most-overdue-customer ranking.
    Deliberately ALL customers, not top-N, since concentration/repeat-
    contribution percentages need the true denominator, not an
    approximation from a truncated top list."""

    customer_id: str
    customer_name: str
    currency_code: str
    revenue: Decimal
    invoice_count: int


def get_customer_revenue_all(db: Session, organization_id: str) -> list[CustomerRevenueRow]:
    rows = db.execute(
        select(
            Customer.id,
            Customer.name,
            Invoice.currency_code,
            func.sum(Invoice.total),
            func.count(Invoice.id),
        )
        .select_from(Invoice)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(Invoice.organization_id == organization_id)
        .group_by(Customer.id, Customer.name, Invoice.currency_code)
    ).all()
    return [
        CustomerRevenueRow(
            customer_id=customer_id,
            customer_name=name,
            currency_code=currency_code,
            revenue=revenue,
            invoice_count=count,
        )
        for customer_id, name, currency_code, revenue, count in rows
    ]


@dataclass(frozen=True)
class CustomerOverdueRow:
    customer_id: str
    customer_name: str
    currency_code: str
    overdue_total: Decimal
    overdue_invoice_count: int
    oldest_due_date: date


def get_customer_overdue_totals(
    db: Session, organization_id: str, *, today_local: date
) -> list[CustomerOverdueRow]:
    """Overdue (due_date < today_local, not paid) balances grouped by
    customer + currency -- the base row set for "most overdue customers"
    and the at-risk heuristic in metrics.py. A single query; the caller
    sorts/limits in Python, matching get_top_customers' own convention."""
    rows = db.execute(
        select(
            Customer.id,
            Customer.name,
            Invoice.currency_code,
            func.sum(Invoice.total),
            func.count(Invoice.id),
            func.min(Invoice.due_date),
        )
        .select_from(Invoice)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(
            Invoice.organization_id == organization_id,
            Invoice.payment_status != PaymentStatus.paid.value,
            Invoice.due_date.is_not(None),
            Invoice.due_date < today_local,
        )
        .group_by(Customer.id, Customer.name, Invoice.currency_code)
    ).all()
    return [
        CustomerOverdueRow(
            customer_id=customer_id,
            customer_name=name,
            currency_code=currency_code,
            overdue_total=total,
            overdue_invoice_count=count,
            oldest_due_date=oldest_due,
        )
        for customer_id, name, currency_code, total, count, oldest_due in rows
    ]


def get_customer_open_invoice_counts(db: Session, organization_id: str) -> dict[str, int]:
    """{customer_id: count of currently-unpaid invoices} -- every unpaid
    invoice, not just overdue ones, feeding the "N consecutive unpaid
    invoices" at-risk rule in metrics.py (a customer with several
    invoices outstanding at once, none of them necessarily overdue yet,
    is a distinct risk signal from "has an old overdue balance")."""
    rows = db.execute(
        select(Invoice.customer_id, func.count(Invoice.id))
        .where(
            Invoice.organization_id == organization_id,
            Invoice.customer_id.is_not(None),
            Invoice.payment_status != PaymentStatus.paid.value,
        )
        .group_by(Invoice.customer_id)
    ).all()
    return {customer_id: count for customer_id, count in rows}


def get_payment_delay_observations(
    db: Session, organization_id: str, *, customer_id: str | None = None
) -> list[int]:
    """Days between an invoice's due_date (or, when no due_date was set,
    its created_at date) and its paid_at -- one integer per invoice with
    a real paid_at on file, oldest-observation-basis, negative values
    (paid early) included deliberately, since excluding them would bias
    the average toward late payers only. Only invoices with paid_at IS
    NOT NULL are ever included -- see Invoice.paid_at's own docstring for
    why a historical invoice marked paid before that column existed is
    honestly excluded here, not guessed at."""
    query = select(Invoice.due_date, Invoice.created_at, Invoice.paid_at).where(
        Invoice.organization_id == organization_id,
        Invoice.paid_at.is_not(None),
    )
    if customer_id is not None:
        query = query.where(Invoice.customer_id == customer_id)

    rows = db.execute(query).all()
    observations: list[int] = []
    for due_date, created_at, paid_at in rows:
        paid_at = _aware(paid_at)
        reference_date = due_date if due_date is not None else _aware(created_at).date()
        observations.append((paid_at.date() - reference_date).days)
    return observations


@dataclass(frozen=True)
class ProductMonthRevenueRow:
    product_id: str
    product_name: str
    currency_code: str
    month: str  # "YYYY-MM"
    revenue: Decimal


def get_product_monthly_revenue(
    db: Session, organization_id: str, month_starts: list[datetime]
) -> list[ProductMonthRevenueRow]:
    """Revenue per (product, currency, month) for every month in
    `month_starts` (oldest first) -- the base series for product trend/
    decline detection in metrics.py. Bucketed in Python from one bounded
    query, matching app.product_analytics' and every other calculator's
    identical "no portable cross-backend truncate-to-month" rationale."""
    range_start = month_starts[0]
    rows = db.execute(
        select(
            Product.id,
            Product.name,
            Invoice.currency_code,
            Invoice.created_at,
            InvoiceLineItem.line_total,
        )
        .select_from(InvoiceLineItem)
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .join(Product, Product.id == InvoiceLineItem.product_id)
        .where(
            Invoice.organization_id == organization_id,
            InvoiceLineItem.product_id.is_not(None),
            Invoice.created_at >= range_start,
        )
    ).all()

    month_keys = [start.strftime("%Y-%m") for start in month_starts]
    buckets: dict[tuple[str, str, str], Decimal] = {}
    names: dict[str, str] = {}
    for product_id, name, currency_code, created_at, line_total in rows:
        names[product_id] = name
        key = (product_id, currency_code, _aware(created_at).strftime("%Y-%m"))
        if key[2] in month_keys:
            buckets[key] = buckets.get(key, Decimal("0")) + line_total

    return [
        ProductMonthRevenueRow(
            product_id=product_id,
            product_name=names[product_id],
            currency_code=currency_code,
            month=month,
            revenue=revenue,
        )
        for (product_id, currency_code, month), revenue in sorted(buckets.items())
    ]


def get_product_quantity_sold(db: Session, organization_id: str) -> dict[tuple[str, str], Decimal]:
    """{(product_id, currency_code): total quantity sold, all-time} --
    pairs with app.product_analytics.get_revenue_by_product (revenue +
    invoice_count) so metrics.py's products section has quantity too,
    without app.product_analytics itself needing a new return shape for
    a dimension only this module needs."""
    rows = db.execute(
        select(Product.id, Invoice.currency_code, func.sum(InvoiceLineItem.quantity))
        .select_from(InvoiceLineItem)
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .join(Product, Product.id == InvoiceLineItem.product_id)
        .where(
            Invoice.organization_id == organization_id,
            InvoiceLineItem.product_id.is_not(None),
        )
        .group_by(Product.id, Invoice.currency_code)
    ).all()
    return {(product_id, currency_code): qty for product_id, currency_code, qty in rows}


def get_receivables_snapshot(
    db: Session, organization_id: str, *, as_of: date
) -> dict[str, tuple[Decimal, Decimal]]:
    """{currency_code: (outstanding_total, overdue_total)} AS OF a given
    past date -- a conservative historical reconstruction powering the
    Executive KPIs' "previous period" comparison for these two stock
    (point-in-time balance) metrics, which have no dedicated history
    table. An invoice counts as outstanding-as-of `as_of` if it existed
    by then (created_at <= as_of) and either isn't currently paid, or its
    real paid_at is after `as_of`. A currently-paid invoice with NO
    paid_at on file (paid before that column existed -- see
    Invoice.paid_at's own docstring) is always treated as already paid by
    any `as_of` date -- the safe, conservative assumption that can only
    ever UNDER-count historical outstanding, never over-count it. See
    docs/financial_dashboard.md's limitations section."""
    as_of_end = datetime.combine(as_of, datetime.max.time()).replace(tzinfo=timezone.utc)
    rows = db.execute(
        select(Invoice.currency_code, Invoice.total, Invoice.payment_status, Invoice.paid_at, Invoice.due_date).where(
            Invoice.organization_id == organization_id, Invoice.created_at <= as_of_end
        )
    ).all()
    outstanding: dict[str, Decimal] = {}
    overdue: dict[str, Decimal] = {}
    for currency_code, total, payment_status, paid_at, due_date in rows:
        if payment_status == PaymentStatus.paid.value:
            if paid_at is None:
                continue
            if _aware(paid_at) <= as_of_end:
                continue
        outstanding[currency_code] = outstanding.get(currency_code, Decimal("0")) + total
        if due_date is not None and due_date < as_of:
            overdue[currency_code] = overdue.get(currency_code, Decimal("0")) + total
    return {
        code: (outstanding.get(code, Decimal("0")), overdue.get(code, Decimal("0"))) for code in outstanding
    }


@dataclass(frozen=True)
class MonthlyRevenueRow:
    """One (currency, month)'s invoiced total, collected total, and
    invoice count -- the base series for the Revenue trends section
    (monthly revenue/collections/invoice-count charts, rolling averages,
    MoM/YoY). `invoiced` is booked revenue (Invoice.total, by
    created_at's month) -- the same "revenue means booked, not collected"
    convention as app.analytics.calculators.revenue. `collected` is the
    subset actually paid (Invoice.total, by paid_at's month, only where
    paid_at is on file) -- an invoice created in one month and paid in a
    later month contributes `invoiced` to the first and `collected` to
    the second, never both to the same month, and never counted at all
    in `collected` if it predates the paid_at column (see Invoice.paid_at's
    own docstring)."""

    month: str  # "YYYY-MM"
    currency_code: str
    invoiced: Decimal
    collected: Decimal
    invoice_count: int


def get_monthly_revenue_series(
    db: Session, organization_id: str, month_starts: list[datetime]
) -> list[MonthlyRevenueRow]:
    """Revenue per (currency, month) for every month in `month_starts`
    (oldest first) -- one bounded query, bucketed in Python, matching
    get_product_monthly_revenue's identical rationale above. Fetches any
    invoice either CREATED or PAID within the requested range, since an
    invoice created before the range can still contribute a `collected`
    figure to a month inside it."""
    range_start = month_starts[0]
    rows = db.execute(
        select(Invoice.currency_code, Invoice.created_at, Invoice.paid_at, Invoice.total).where(
            Invoice.organization_id == organization_id,
            or_(Invoice.created_at >= range_start, Invoice.paid_at >= range_start),
        )
    ).all()

    month_keys = [start.strftime("%Y-%m") for start in month_starts]
    invoiced: dict[tuple[str, str], Decimal] = {}
    collected: dict[tuple[str, str], Decimal] = {}
    counts: dict[tuple[str, str], int] = {}

    for currency_code, created_at, paid_at, total in rows:
        created_key = _aware(created_at).strftime("%Y-%m")
        if created_key in month_keys:
            key = (currency_code, created_key)
            invoiced[key] = invoiced.get(key, Decimal("0")) + total
            counts[key] = counts.get(key, 0) + 1
        if paid_at is not None:
            paid_key = _aware(paid_at).strftime("%Y-%m")
            if paid_key in month_keys:
                key = (currency_code, paid_key)
                collected[key] = collected.get(key, Decimal("0")) + total

    keys = sorted(set(invoiced) | set(collected))
    return [
        MonthlyRevenueRow(
            month=month,
            currency_code=currency_code,
            invoiced=invoiced.get((currency_code, month), Decimal("0")),
            collected=collected.get((currency_code, month), Decimal("0")),
            invoice_count=counts.get((currency_code, month), 0),
        )
        for currency_code, month in keys
    ]


@dataclass(frozen=True)
class QuoteValueByCurrency:
    currency_code: str
    quoted_value: Decimal  # every quote ever created, any status
    converted_value: Decimal  # quotes whose stored status is "converted"


def get_quote_value_by_currency(db: Session, organization_id: str) -> list[QuoteValueByCurrency]:
    """Total value of every quote ever created vs. the subset that
    actually converted to an invoice -- "quoted value versus converted
    value," per currency. Uses the STORED status column for "converted"
    (a terminal, never-reverted fact -- see app.quote_effective_status),
    not the effective-status helper, since draft/sent/expired don't need
    disambiguation here."""
    rows = db.execute(
        select(Quote.currency_code, Quote.total, Quote.status).where(
            Quote.organization_id == organization_id, Quote.active.is_(True)
        )
    ).all()
    totals: dict[str, dict[str, Decimal]] = {}
    for currency_code, total, status in rows:
        bucket = totals.setdefault(currency_code, {"quoted": Decimal("0"), "converted": Decimal("0")})
        bucket["quoted"] += total
        if status == QuoteStatus.converted.value:
            bucket["converted"] += total
    return [
        QuoteValueByCurrency(currency_code=code, quoted_value=v["quoted"], converted_value=v["converted"])
        for code, v in sorted(totals.items())
    ]
