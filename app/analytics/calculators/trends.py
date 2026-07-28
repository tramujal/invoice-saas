"""Trend calculators -- period-over-period comparisons and multi-period
evolution series, built entirely on top of the metric calculators Phase
16A already wrote (app.analytics.calculators.{invoices,revenue,
customers}) plus the two shared primitives this phase adds
(app.analytics.comparison.compare_periods, app.analytics.trend_direction).

Nothing here recomputes a metric's own value -- get_revenue_trend, for
example, calls revenue.get_revenue_by_currency twice (once per window)
and hands both results to compare_periods; it never sums an Invoice
table itself. This is the same "calculator delegates to calculator,
never duplicates a query" discipline app.analytics.calculators.quotes
already established for quote-pipeline figures.

Series functions intentionally return one generic shape (SeriesPoint),
not a bespoke type per metric -- see this phase's own instruction ("Do
not build chart-specific structures. The frontend should consume generic
series."). Bucketing is done in Python from one bounded query per
series, the same reasoning
app.analytics.calculators.invoices.get_monthly_invoice_counts already
documents (no portable cross-backend "truncate to month/quarter/year"
SQL function). The existing month-only bucketing functions in
invoices.py/revenue.py are left untouched (still used by Phase 16A's
dashboard endpoint) -- this module's bucketing is a second, generic
implementation parameterized by granularity, not a refactor of that
tested code, so Phase 16A/16B behavior cannot regress.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.calculators import customers as customers_calc
from app.analytics.calculators import invoices as invoices_calc
from app.analytics.calculators import revenue as revenue_calc
from app.analytics.comparison import PeriodComparison, compare_periods
from app.analytics.primitives import quantize_money
from app.analytics.time_windows import TimeWindow
from app.models import Customer, Invoice, Quote
from app.quote_status import QuoteStatus

# --- Period-over-period comparisons -----------------------------------


def get_revenue_trend(
    db: Session, organization_id: str, *, current: TimeWindow, previous: TimeWindow
) -> dict[str, PeriodComparison]:
    """{currency_code: PeriodComparison}, one entry per currency seen in
    either window -- never combined across currencies. A currency
    present in only one of the two windows still gets a comparison (the
    other side defaults to 0), matching get_revenue_growth's own
    "no baseline yet" handling one level up in compare_periods."""
    current_totals = revenue_calc.get_revenue_by_currency(db, organization_id, window=current)
    previous_totals = revenue_calc.get_revenue_by_currency(db, organization_id, window=previous)
    codes = set(current_totals) | set(previous_totals)
    return {
        code: compare_periods(
            current_totals.get(code, Decimal("0")), previous_totals.get(code, Decimal("0"))
        )
        for code in sorted(codes)
    }


def get_invoice_count_trend(
    db: Session, organization_id: str, *, current: TimeWindow, previous: TimeWindow
) -> PeriodComparison:
    """Currency-agnostic (a count) -- total invoices created in `current`
    vs. `previous`."""
    current_count = invoices_calc.get_invoice_counts(db, organization_id, window=current).total
    previous_count = invoices_calc.get_invoice_counts(db, organization_id, window=previous).total
    return compare_periods(Decimal(current_count), Decimal(previous_count))


def get_customer_growth_trend(
    db: Session, organization_id: str, *, current: TimeWindow, previous: TimeWindow
) -> PeriodComparison:
    """New customers created in `current` vs. `previous` -- distinct from
    AnalyticsService.customer_retention (all-time, lifetime), this is a
    windowed acquisition-rate comparison."""
    current_count = customers_calc.get_customer_growth(db, organization_id, window=current)
    previous_count = customers_calc.get_customer_growth(db, organization_id, window=previous)
    return compare_periods(Decimal(current_count), Decimal(previous_count))


def _count_quotes_created(db: Session, organization_id: str, window: TimeWindow) -> int:
    """Quotes CREATED in `window`, by Quote.created_at -- a plain creation
    count, deliberately not using effective/decided status (that's
    app.quote_analytics' concern for pipeline figures). Mirrors
    get_invoice_counts' own "created in this window" semantics exactly,
    just without the effective-status breakdown invoices need."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Quote)
            .where(
                Quote.organization_id == organization_id,
                Quote.created_at >= window.start,
                Quote.created_at < window.end,
            )
        )
        or 0
    )


def get_quote_count_trend(
    db: Session, organization_id: str, *, current: TimeWindow, previous: TimeWindow
) -> PeriodComparison:
    """Quotes created in `current` vs. `previous` -- currency-agnostic,
    like get_invoice_count_trend."""
    current_count = _count_quotes_created(db, organization_id, current)
    previous_count = _count_quotes_created(db, organization_id, previous)
    return compare_periods(Decimal(current_count), Decimal(previous_count))


# --- Generic multi-period evolution series ------------------------------


class SeriesGranularity(str, Enum):
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


@dataclass(frozen=True)
class SeriesPoint:
    """One point in a generic evolution series -- `period` is a bucket
    label whose format depends on granularity ("2026-07" monthly,
    "2026-Q3" quarterly, "2026" yearly), `currency_code` is None for
    currency-agnostic series (invoice/customer/quote counts)."""

    period: str
    value: Decimal
    currency_code: str | None = None


def _bucket_key(moment: datetime, granularity: SeriesGranularity) -> str:
    if granularity == SeriesGranularity.monthly:
        return moment.strftime("%Y-%m")
    if granularity == SeriesGranularity.quarterly:
        quarter = (moment.month - 1) // 3 + 1
        return f"{moment.year}-Q{quarter}"
    return str(moment.year)


def get_revenue_series(
    db: Session,
    organization_id: str,
    period_starts: list[datetime],
    granularity: SeriesGranularity,
) -> list[SeriesPoint]:
    """Revenue trend, one SeriesPoint per (period, currency) pair --
    zero-filled so every currency seen anywhere in range gets a full,
    contiguous series (matches
    app.analytics.calculators.revenue.get_monthly_revenue_series' own
    zero-fill rationale, generalized to any granularity)."""
    range_start = period_starts[0]
    rows = db.execute(
        select(Invoice.created_at, Invoice.total, Invoice.currency_code).where(
            Invoice.organization_id == organization_id, Invoice.created_at >= range_start
        )
    ).all()

    period_keys = [_bucket_key(start, granularity) for start in period_starts]
    currencies_seen = {currency_code for _, _, currency_code in rows}
    buckets: dict[tuple[str, str], Decimal] = {
        (key, currency_code): Decimal("0") for key in period_keys for currency_code in currencies_seen
    }
    for created_at, total, currency_code in rows:
        key = (_bucket_key(created_at, granularity), currency_code)
        if key in buckets:
            buckets[key] += total

    return [
        SeriesPoint(period=period, value=quantize_money(value), currency_code=currency_code)
        for (period, currency_code), value in sorted(buckets.items())
    ]


def get_invoice_count_series(
    db: Session,
    organization_id: str,
    period_starts: list[datetime],
    granularity: SeriesGranularity,
) -> list[SeriesPoint]:
    """Invoice-count trend, one SeriesPoint per period -- currency-
    agnostic (a count), mirroring get_monthly_invoice_counts generalized
    to any granularity."""
    range_start = period_starts[0]
    rows = db.execute(
        select(Invoice.created_at).where(
            Invoice.organization_id == organization_id, Invoice.created_at >= range_start
        )
    ).all()

    period_keys = [_bucket_key(start, granularity) for start in period_starts]
    counts: dict[str, int] = {key: 0 for key in period_keys}
    for (created_at,) in rows:
        key = _bucket_key(created_at, granularity)
        if key in counts:
            counts[key] += 1

    return [SeriesPoint(period=key, value=Decimal(counts[key])) for key in sorted(counts)]


def get_customer_count_series(
    db: Session,
    organization_id: str,
    period_starts: list[datetime],
    granularity: SeriesGranularity,
) -> list[SeriesPoint]:
    """New-customer count trend, one SeriesPoint per period -- currency-
    agnostic, same bucketing shape as get_invoice_count_series."""
    range_start = period_starts[0]
    rows = db.execute(
        select(Customer.created_at).where(
            Customer.organization_id == organization_id, Customer.created_at >= range_start
        )
    ).all()

    period_keys = [_bucket_key(start, granularity) for start in period_starts]
    counts: dict[str, int] = {key: 0 for key in period_keys}
    for (created_at,) in rows:
        key = _bucket_key(created_at, granularity)
        if key in counts:
            counts[key] += 1

    return [SeriesPoint(period=key, value=Decimal(counts[key])) for key in sorted(counts)]


def get_quote_conversion_series(
    db: Session,
    organization_id: str,
    period_starts: list[datetime],
    granularity: SeriesGranularity,
) -> list[SeriesPoint]:
    """Converted-quote count trend, one SeriesPoint per period -- by
    Quote.updated_at, the same column
    app.quote_analytics.get_quote_monthly_conversions already uses (no
    separate converted_at audit column exists; see that module's own
    docstring)."""
    range_start = period_starts[0]
    rows = db.execute(
        select(Quote.updated_at).where(
            Quote.organization_id == organization_id,
            Quote.status == QuoteStatus.converted.value,
            Quote.updated_at >= range_start,
        )
    ).all()

    period_keys = [_bucket_key(start, granularity) for start in period_starts]
    counts: dict[str, int] = {key: 0 for key in period_keys}
    for (updated_at,) in rows:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        key = _bucket_key(updated_at, granularity)
        if key in counts:
            counts[key] += 1

    return [SeriesPoint(period=key, value=Decimal(counts[key])) for key in sorted(counts)]
