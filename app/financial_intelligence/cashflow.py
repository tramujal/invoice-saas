"""Receivables-only deterministic calculations: AR aging buckets,
payment-delay statistics, and the collections calendar. Deliberately
never "profit" or "net cash flow" -- this application tracks no
expenses anywhere, so there is no P&L concept these functions could
honestly compute (see CASHFLOW_DISCLAIMER in schemas.py).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy.orm import Session

from app.financial_intelligence import queries
from app.financial_intelligence.queries import OpenInvoiceRow

# Below this many real (paid_at-backed) observations, a payment-delay
# average is not shown as a number a caller should act on -- see
# DelayStats.available below.
MIN_PAYMENT_DELAY_OBSERVATIONS = 5

AGING_BUCKET_NOT_YET_DUE = "not_yet_due"
AGING_BUCKET_1_30 = "overdue_1_30"
AGING_BUCKET_31_60 = "overdue_31_60"
AGING_BUCKET_61_90 = "overdue_61_90"
AGING_BUCKET_90_PLUS = "overdue_90_plus"
AGING_BUCKET_ORDER = (
    AGING_BUCKET_NOT_YET_DUE,
    AGING_BUCKET_1_30,
    AGING_BUCKET_31_60,
    AGING_BUCKET_61_90,
    AGING_BUCKET_90_PLUS,
)


def _bucket_for(days_overdue: int) -> str:
    if days_overdue <= 0:
        return AGING_BUCKET_NOT_YET_DUE
    if days_overdue <= 30:
        return AGING_BUCKET_1_30
    if days_overdue <= 60:
        return AGING_BUCKET_31_60
    if days_overdue <= 90:
        return AGING_BUCKET_61_90
    return AGING_BUCKET_90_PLUS


@dataclass(frozen=True)
class AgingBucketAmount:
    bucket: str
    currency_code: str
    amount: Decimal
    invoice_count: int
    percent_of_total: Decimal | None


@dataclass(frozen=True)
class AgingResult:
    buckets: list[AgingBucketAmount]
    invoices_missing_due_date: int


def compute_aging_buckets(db: Session, organization_id: str, *, today_local: date) -> AgingResult:
    """AR aging, grouped by (bucket, currency) -- only invoices with a
    due_date on file can be bucketed at all; unpaid invoices with no
    due_date (every historical invoice created before that column
    existed, or one deliberately created without one) are counted
    separately as invoices_missing_due_date, never silently placed in
    "not yet due" or dropped."""
    open_invoices = queries.get_open_invoices(db, organization_id)

    totals: dict[tuple[str, str], Decimal] = {}
    counts: dict[tuple[str, str], int] = {}
    currency_totals: dict[str, Decimal] = {}
    missing_due_date = 0

    for inv in open_invoices:
        if inv.due_date is None:
            missing_due_date += 1
            continue
        bucket = _bucket_for((today_local - inv.due_date).days)
        key = (bucket, inv.currency_code)
        totals[key] = totals.get(key, Decimal("0")) + inv.total
        counts[key] = counts.get(key, 0) + 1
        currency_totals[inv.currency_code] = currency_totals.get(inv.currency_code, Decimal("0")) + inv.total

    buckets: list[AgingBucketAmount] = []
    currencies = sorted({code for _, code in totals})
    for currency_code in currencies:
        currency_total = currency_totals.get(currency_code, Decimal("0"))
        for bucket_name in AGING_BUCKET_ORDER:
            key = (bucket_name, currency_code)
            if key not in totals:
                continue
            amount = totals[key]
            percent = (
                (amount / currency_total * 100).quantize(Decimal("0.01"))
                if currency_total > 0
                else None
            )
            buckets.append(
                AgingBucketAmount(
                    bucket=bucket_name,
                    currency_code=currency_code,
                    amount=amount.quantize(Decimal("0.01")),
                    invoice_count=counts[key],
                    percent_of_total=percent,
                )
            )

    return AgingResult(buckets=buckets, invoices_missing_due_date=missing_due_date)


@dataclass(frozen=True)
class DelayStats:
    available: bool
    sample_size: int
    average_days: Decimal | None
    median_days: Decimal | None


def compute_payment_delay_stats(
    db: Session, organization_id: str, *, customer_id: str | None = None
) -> DelayStats:
    """Org-wide (customer_id=None) or one customer's own payment-delay
    statistics, built entirely from real Invoice.paid_at observations --
    see queries.get_payment_delay_observations. Honestly reports
    available=False below MIN_PAYMENT_DELAY_OBSERVATIONS rather than
    showing a number computed from too few (or zero) real data points."""
    observations = queries.get_payment_delay_observations(db, organization_id, customer_id=customer_id)
    if len(observations) < MIN_PAYMENT_DELAY_OBSERVATIONS:
        return DelayStats(
            available=False, sample_size=len(observations), average_days=None, median_days=None
        )
    average = Decimal(sum(observations)) / Decimal(len(observations))
    return DelayStats(
        available=True,
        sample_size=len(observations),
        average_days=average.quantize(Decimal("0.1")),
        median_days=Decimal(str(median(observations))),
    )


@dataclass(frozen=True)
class CollectionsCalendarPointResult:
    period_start: date
    period_end: date
    currency_code: str
    known_amount: Decimal
    invoice_count: int


def _expected_collection_date(
    invoice: OpenInvoiceRow, *, today_local: date, org_delay: DelayStats
) -> date:
    """The date this invoice is realistically expected to be collected:
    its own due_date if it isn't overdue yet (assume on-time payment,
    the honest default absent any signal otherwise); its due_date PLUS
    the org's own average payment delay if it's already overdue (a
    customer-specific delay isn't looked up per invoice here -- that
    refinement lives in forecasting.py's expected-collections VIEW,
    which calls this same building block per customer where it has
    enough observations); today, when there's no due_date at all (the
    least-wrong assumption for an invoice with no scheduling
    information whatsoever).

    Never returns a date before today_local: an already-overdue invoice
    with no org-wide delay history yet to project forward would
    otherwise compute an expected date still in the past, which
    build_collections_calendar's own [today_local, horizon_end) window
    would then silently exclude -- dropping a real, currently-owed
    invoice from the calendar entirely rather than showing it as
    expected as soon as possible. Clamping to today_local is the honest
    "we don't know exactly when, but it's owed right now" signal."""
    if invoice.due_date is None:
        return today_local
    if invoice.due_date >= today_local:
        return invoice.due_date
    if org_delay.available and org_delay.average_days is not None:
        return max(invoice.due_date + timedelta(days=int(org_delay.average_days)), today_local)
    return today_local


def build_collections_calendar(
    db: Session,
    organization_id: str,
    *,
    today_local: date,
    horizon_days: int,
    granularity: str = "week",
) -> list[CollectionsCalendarPointResult]:
    """Buckets every currently-open invoice's *expected* collection date
    (see _expected_collection_date) into day/week/month periods within
    [today_local, today_local + horizon_days) -- the deterministic
    "known" component of the expected-collections forecast
    (forecasting.py adds a statistical *projected* component on top for
    periods beyond any currently-open invoice's due date). Every amount
    here traces back to a real, currently-open invoice -- nothing is
    fabricated."""
    if granularity not in ("day", "week", "month"):
        raise ValueError(f"Unsupported granularity: {granularity!r}")

    org_delay = compute_payment_delay_stats(db, organization_id)
    open_invoices = queries.get_open_invoices(db, organization_id)
    horizon_end = today_local + timedelta(days=horizon_days)

    def period_bounds(d: date) -> tuple[date, date]:
        if granularity == "day":
            return d, d + timedelta(days=1)
        if granularity == "week":
            start = d - timedelta(days=d.weekday())
            return start, start + timedelta(days=7)
        start = d.replace(day=1)
        next_month = start.month % 12 + 1
        next_year = start.year + (1 if start.month == 12 else 0)
        return start, start.replace(year=next_year, month=next_month)

    buckets: dict[tuple[date, date, str], Decimal] = {}
    counts: dict[tuple[date, date, str], int] = {}
    for inv in open_invoices:
        expected = _expected_collection_date(inv, today_local=today_local, org_delay=org_delay)
        if expected < today_local or expected >= horizon_end:
            continue
        period_start, period_end = period_bounds(expected)
        key = (period_start, period_end, inv.currency_code)
        buckets[key] = buckets.get(key, Decimal("0")) + inv.total
        counts[key] = counts.get(key, 0) + 1

    return [
        CollectionsCalendarPointResult(
            period_start=period_start,
            period_end=period_end,
            currency_code=currency_code,
            known_amount=amount.quantize(Decimal("0.01")),
            invoice_count=counts[(period_start, period_end, currency_code)],
        )
        for (period_start, period_end, currency_code), amount in sorted(buckets.items())
    ]
