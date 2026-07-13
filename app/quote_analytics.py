"""Shared quote-pipeline analytics queries -- used by both the dashboard
router (app/routers/dashboard.py) and the Business Insights engine
(app/insights/engine.py), matching the exact reuse rationale
app.product_analytics already established: one query, more than one
caller, never duplicated.

Every count/sum here is scoped to active=True quotes only (archived
quotes are hidden from the current pipeline view, same as
app.product_analytics excluding archived products by default) and uses
each quote's *effective* status (see app.quote_effective_status), never
the raw stored column, so a quote whose expiry_date has silently passed
is never miscounted as still "sent."

"This month" figures (accepted/rejected/converted) are derived from
updated_at, the same column every status-changing write already touches
(mark_quote_accepted_record/mark_quote_rejected_record/
convert_quote_to_invoice all commit through the ORM's onupdate=func.now())
-- there is no separate accepted_at/rejected_at audit column, matching
this app's existing precedent of not tracking a dedicated timestamp per
status transition (Invoice has no paid_at either).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer, Organization, Quote
from app.org_time import get_organization_today
from app.quote_effective_status import get_effective_quote_status
from app.quote_status import QuoteStatus

QUOTE_EXPIRING_SOON_WINDOW_DAYS = 7
QUOTE_LIST_DETAIL_LIMIT = 200
REPEATED_REJECTION_MIN_COUNT = 2


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _effective_statuses(db: Session, organization_id: str) -> list[tuple[Quote, QuoteStatus]]:
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    quotes = db.scalars(
        select(Quote).where(
            Quote.organization_id == organization_id, Quote.active.is_(True)
        )
    ).all()
    return [(q, get_effective_quote_status(q, today_local)) for q in quotes]


@dataclass
class QuoteCurrencyPipeline:
    currency_code: str
    revenue_in_quotes: Decimal
    projected_revenue: Decimal
    accepted_this_month: int
    rejected_this_month: int
    converted_this_month: int


@dataclass
class QuotePipelineData:
    counts_by_status: dict[str, int]
    acceptance_rate_percent: float | None
    by_currency: list[QuoteCurrencyPipeline]


def get_quote_pipeline_summary(db: Session, organization_id: str) -> QuotePipelineData:
    rows = _effective_statuses(db, organization_id)
    now = datetime.now(timezone.utc)
    this_month_start = _month_start(now)

    counts_by_status: dict[str, int] = {s.value: 0 for s in QuoteStatus}
    accepted_total = 0
    rejected_total = 0

    by_currency_pending: dict[str, Decimal] = {}
    by_currency_accepted_month: dict[str, int] = {}
    by_currency_rejected_month: dict[str, int] = {}
    by_currency_converted_month: dict[str, int] = {}
    by_currency_accepted_total: dict[str, int] = {}
    by_currency_rejected_total: dict[str, int] = {}

    for quote, effective in rows:
        counts_by_status[effective.value] += 1
        code = quote.currency_code

        updated_at = quote.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        is_this_month = updated_at >= this_month_start

        if effective in (QuoteStatus.draft, QuoteStatus.sent):
            by_currency_pending[code] = by_currency_pending.get(code, Decimal("0")) + quote.total
        elif effective == QuoteStatus.accepted:
            accepted_total += 1
            by_currency_accepted_total[code] = by_currency_accepted_total.get(code, 0) + 1
            if is_this_month:
                by_currency_accepted_month[code] = by_currency_accepted_month.get(code, 0) + 1
        elif effective == QuoteStatus.rejected:
            rejected_total += 1
            by_currency_rejected_total[code] = by_currency_rejected_total.get(code, 0) + 1
            if is_this_month:
                by_currency_rejected_month[code] = by_currency_rejected_month.get(code, 0) + 1
        elif effective == QuoteStatus.converted and is_this_month:
            by_currency_converted_month[code] = by_currency_converted_month.get(code, 0) + 1

    acceptance_rate_percent: float | None = None
    if accepted_total + rejected_total > 0:
        acceptance_rate_percent = (accepted_total / (accepted_total + rejected_total)) * 100

    currencies = set(by_currency_pending) | set(by_currency_accepted_total) | set(
        by_currency_rejected_total
    ) | set(by_currency_converted_month)

    by_currency: list[QuoteCurrencyPipeline] = []
    for code in sorted(currencies):
        pending = by_currency_pending.get(code, Decimal("0"))
        currency_accepted = by_currency_accepted_total.get(code, 0)
        currency_rejected = by_currency_rejected_total.get(code, 0)
        currency_rate = (
            currency_accepted / (currency_accepted + currency_rejected)
            if (currency_accepted + currency_rejected) > 0
            else None
        )
        projected = pending * Decimal(str(currency_rate)) if currency_rate is not None else Decimal("0")
        by_currency.append(
            QuoteCurrencyPipeline(
                currency_code=code,
                revenue_in_quotes=pending.quantize(Decimal("0.01")),
                projected_revenue=projected.quantize(Decimal("0.01")),
                accepted_this_month=by_currency_accepted_month.get(code, 0),
                rejected_this_month=by_currency_rejected_month.get(code, 0),
                converted_this_month=by_currency_converted_month.get(code, 0),
            )
        )

    return QuotePipelineData(
        counts_by_status=counts_by_status,
        acceptance_rate_percent=acceptance_rate_percent,
        by_currency=by_currency,
    )


@dataclass
class QuoteMonthlyConversion:
    month: str
    converted_count: int


def get_quote_monthly_conversions(
    db: Session, organization_id: str, month_starts: list[datetime]
) -> list[QuoteMonthlyConversion]:
    """Converted-quote counts per month, for the same trailing window the
    dashboard's monthly_summary already uses -- bucketed in Python from a
    single bounded query, matching app.routers.dashboard's own convention
    for month bucketing (no portable SQL "truncate to month" function)."""
    range_start = month_starts[0]
    rows = db.execute(
        select(Quote.updated_at).where(
            Quote.organization_id == organization_id,
            Quote.status == QuoteStatus.converted.value,
            Quote.updated_at >= range_start,
        )
    ).all()

    counts: dict[str, int] = {start.strftime("%Y-%m"): 0 for start in month_starts}
    for (updated_at,) in rows:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        key = updated_at.strftime("%Y-%m")
        if key in counts:
            counts[key] += 1

    return [QuoteMonthlyConversion(month=key, converted_count=counts[key]) for key in sorted(counts)]


@dataclass
class QuoteDetail:
    quote_id: str
    quote_number: int
    customer_name: str | None
    total: Decimal
    currency_code: str
    expiry_date: object | None


def get_quotes_pending_response(db: Session, organization_id: str) -> list[QuoteDetail]:
    """Quotes whose effective status is "sent" -- awaiting the customer's
    decision. Mirrors app.insights.queries.get_overdue_invoice_details'
    "single bounded query, derive everything else in Python" shape."""
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    rows = db.scalars(
        select(Quote)
        .options(selectinload(Quote.customer))
        .where(
            Quote.organization_id == organization_id,
            Quote.active.is_(True),
            Quote.status == QuoteStatus.sent.value,
        )
        .order_by(Quote.created_at.asc())
        .limit(QUOTE_LIST_DETAIL_LIMIT)
    ).all()
    return [
        QuoteDetail(
            quote_id=q.id,
            quote_number=q.quote_number,
            customer_name=q.customer_name,
            total=q.total,
            currency_code=q.currency_code,
            expiry_date=q.expiry_date,
        )
        for q in rows
        if get_effective_quote_status(q, today_local) == QuoteStatus.sent
    ]


def get_quotes_expiring_soon(db: Session, organization_id: str) -> list[QuoteDetail]:
    """Unpaid... rather, undecided ("sent") quotes whose expiry_date falls
    within QUOTE_EXPIRING_SOON_WINDOW_DAYS -- a distinct, smaller-urgency
    signal from "already expired," mirroring
    app.insights.queries.get_due_soon_invoice_details exactly."""
    from datetime import timedelta

    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    window_end = today_local + timedelta(days=QUOTE_EXPIRING_SOON_WINDOW_DAYS)
    rows = db.scalars(
        select(Quote)
        .options(selectinload(Quote.customer))
        .where(
            Quote.organization_id == organization_id,
            Quote.active.is_(True),
            Quote.status == QuoteStatus.sent.value,
            Quote.expiry_date.is_not(None),
            Quote.expiry_date >= today_local,
            Quote.expiry_date <= window_end,
        )
        .order_by(Quote.expiry_date.asc())
        .limit(QUOTE_LIST_DETAIL_LIMIT)
    ).all()
    return [
        QuoteDetail(
            quote_id=q.id,
            quote_number=q.quote_number,
            customer_name=q.customer_name,
            total=q.total,
            currency_code=q.currency_code,
            expiry_date=q.expiry_date,
        )
        for q in rows
    ]


def get_quotes_expired(db: Session, organization_id: str) -> list[QuoteDetail]:
    """Quotes whose EFFECTIVE status is "expired" -- derived, never a
    stored value (see app.quote_effective_status)."""
    rows = _effective_statuses(db, organization_id)
    return [
        QuoteDetail(
            quote_id=q.id,
            quote_number=q.quote_number,
            customer_name=q.customer_name,
            total=q.total,
            currency_code=q.currency_code,
            expiry_date=q.expiry_date,
        )
        for q, effective in rows
        if effective == QuoteStatus.expired
    ][:QUOTE_LIST_DETAIL_LIMIT]


@dataclass
class RepeatedRejectionCustomer:
    customer_id: str
    customer_name: str
    rejected_count: int


def get_customers_with_repeated_rejections(
    db: Session, organization_id: str, min_count: int = REPEATED_REJECTION_MIN_COUNT
) -> list[RepeatedRejectionCustomer]:
    rows = db.execute(
        select(Customer.id, Customer.name, func.count(Quote.id))
        .join(Quote, Quote.customer_id == Customer.id)
        .where(
            Quote.organization_id == organization_id,
            Quote.status == QuoteStatus.rejected.value,
        )
        .group_by(Customer.id, Customer.name)
        .having(func.count(Quote.id) >= min_count)
    ).all()
    results = [
        RepeatedRejectionCustomer(customer_id=cid, customer_name=name, rejected_count=count)
        for cid, name, count in rows
    ]
    results.sort(key=lambda r: r.rejected_count, reverse=True)
    return results
