from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_permission
from app.effective_status import get_effective_payment_status
from app.models import Customer, Invoice, Organization, User
from app.permissions import Permission
from app.org_time import get_organization_today
from app.payment_status import PaymentStatus
from app.product_analytics import get_revenue_by_product
from app.quote_analytics import get_quote_monthly_conversions, get_quote_pipeline_summary
from app.schemas import (
    CurrencyRevenueSummary,
    DashboardAnalyticsResponse,
    DashboardResponse,
    MonthlyRevenuePoint,
    MonthlySummaryPoint,
    PaymentStatusCountPoint,
    QuoteCurrencyPipelineSummary,
    QuoteMonthlyConversionPoint,
    QuotePipelineSummary,
    QuoteStatusCountPoint,
    TeamRoleCount,
    TeamSummaryResponse,
    TopCustomerRevenue,
    TopProductRevenue,
)
from app.quote_status import QuoteStatus
from app.team_analytics import get_team_summary

router = APIRouter(
    prefix="/organizations/{organization_id}/dashboard", tags=["dashboard"]
)

RECENT_INVOICES_LIMIT = 5
MONTHLY_SUMMARY_MONTHS = 6
TOP_CUSTOMERS_LIMIT = 5
TOP_PRODUCTS_LIMIT = 5


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


def _effective_status_counts(db: Session, organization_id: str) -> dict[str, int]:
    """Invoice counts by EFFECTIVE status (due-date-derived, via
    app.effective_status), not the raw stored payment_status column -- the
    dashboard must agree with every other surface (PDF, email, insights,
    assistant) on what's actually overdue. Fetches just the two columns
    get_effective_payment_status needs (a SQLAlchemy Row already exposes
    them as .payment_status/.due_date, so the exact same helper function
    applies with no separate ORM Invoice object required) and counts in
    Python -- same "simple, portable query" preference as this file's
    other status/currency groupings, rather than a per-database CASE
    expression.
    """
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    rows = db.execute(
        select(Invoice.payment_status, Invoice.due_date).where(
            Invoice.organization_id == organization_id
        )
    ).all()
    counts: dict[str, int] = {}
    for row in rows:
        effective = get_effective_payment_status(row, today_local)
        counts[effective.value] = counts.get(effective.value, 0) + 1
    return counts


def get_dashboard_summary(db: Session, organization_id: str) -> DashboardResponse:
    """The actual dashboard computation, factored out of the route below so
    app.assistant_context can reuse the exact same numbers the dashboard UI
    shows — never a second, potentially-drifting computation of the same
    thing. Callers are responsible for their own authorization check
    (get_dashboard() below calls require_org_member(); the assistant
    context builder relies on its caller having already done so)."""
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
    status_counts = _effective_status_counts(db, organization_id)

    last_month_start, this_month_start = _month_bounds(datetime.now(timezone.utc))

    # Revenue is grouped by currency_code at every step below — never
    # summed across currencies, since e.g. "USD 100 + UYU 1000" isn't a
    # meaningful number. Three separate grouped queries (total/this-month/
    # last-month), matching this file's existing style of straightforward,
    # portable queries over cleverer combined SQL.
    total_by_currency = dict(
        db.execute(
            select(Invoice.currency_code, func.coalesce(func.sum(Invoice.total), 0))
            .where(org_filter)
            .group_by(Invoice.currency_code)
        ).all()
    )
    this_month_by_currency = dict(
        db.execute(
            select(Invoice.currency_code, func.coalesce(func.sum(Invoice.total), 0))
            .where(org_filter, Invoice.created_at >= this_month_start)
            .group_by(Invoice.currency_code)
        ).all()
    )
    last_month_by_currency = dict(
        db.execute(
            select(Invoice.currency_code, func.coalesce(func.sum(Invoice.total), 0))
            .where(
                org_filter,
                Invoice.created_at >= last_month_start,
                Invoice.created_at < this_month_start,
            )
            .group_by(Invoice.currency_code)
        ).all()
    )

    currency_codes = (
        set(total_by_currency) | set(this_month_by_currency) | set(last_month_by_currency)
    )
    revenue_by_currency: list[CurrencyRevenueSummary] = []
    for code in sorted(currency_codes):
        this_month = _quantize_money(this_month_by_currency.get(code, Decimal("0")))
        last_month = _quantize_money(last_month_by_currency.get(code, Decimal("0")))
        growth_percent: Decimal | None = None
        if last_month > 0:
            growth_percent = ((this_month - last_month) / last_month * 100).quantize(
                Decimal("0.01")
            )
        revenue_by_currency.append(
            CurrencyRevenueSummary(
                currency_code=code,
                total_revenue=_quantize_money(total_by_currency.get(code, Decimal("0"))),
                revenue_this_month=this_month,
                revenue_last_month=last_month,
                revenue_growth_percent=growth_percent,
            )
        )

    recent_invoices = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(org_filter)
        .order_by(Invoice.created_at.desc())
        .limit(RECENT_INVOICES_LIMIT)
    ).all()

    return DashboardResponse(
        total_invoices=total_invoices,
        total_customers=total_customers,
        pending_invoices=status_counts.get(PaymentStatus.pending.value, 0),
        paid_invoices=status_counts.get(PaymentStatus.paid.value, 0),
        overdue_invoices=status_counts.get(PaymentStatus.overdue.value, 0),
        revenue_by_currency=revenue_by_currency,
        recent_invoices=list(recent_invoices),
    )


def get_pending_total_by_currency(db: Session, organization_id: str) -> dict[str, Decimal]:
    """Pending-only revenue exposure, grouped by currency — same query
    shape as get_dashboard_summary's total/this-month/last-month currency
    sums above, filtered to payment_status == pending. Not used by any
    existing route; added for app.insights.engine's pending-exposure
    insight, which needs this and nothing else from this file changes."""
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
    return {code: _quantize_money(total) for code, total in rows.items()}


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    require_permission(current_user, organization_id, Permission.dashboard_view, db)
    return get_dashboard_summary(db, organization_id)


def get_dashboard_analytics_data(db: Session, organization_id: str) -> DashboardAnalyticsResponse:
    """Same extraction as get_dashboard_summary above, for the analytics
    endpoint — reused by app.assistant_context so the assistant's monthly
    figures and top-customers list are identical to the dashboard UI's."""
    org_filter = Invoice.organization_id == organization_id

    # --- monthly invoice volume + revenue, last N months ---
    # Bucketed in Python rather than SQL GROUP BY month: SQLite and Postgres
    # don't share a portable "truncate to month" function, and at this app's
    # scale (one org's invoices over a few months) fetching the bounded row
    # set and summing here is simple and correct on both backends.
    #
    # invoice_count is a plain count (currency-agnostic — combining it
    # across currencies is fine, per the same reasoning as total_invoices
    # elsewhere). revenue is bucketed by (month, currency_code) instead and
    # never summed across currencies — see MonthlyRevenuePoint.
    month_starts = _last_n_month_starts(datetime.now(timezone.utc), MONTHLY_SUMMARY_MONTHS)
    range_start = month_starts[0]

    rows = db.execute(
        select(Invoice.created_at, Invoice.total, Invoice.currency_code).where(
            org_filter, Invoice.created_at >= range_start
        )
    ).all()

    invoice_counts: dict[str, int] = {_month_key(start): 0 for start in month_starts}

    # Zero-filled for every (month, currency) pair up front, for every
    # currency that appears anywhere in the window — so each currency gets
    # a full, contiguous MONTHLY_SUMMARY_MONTHS-point series (matching the
    # single-currency chart's previous guarantee) instead of gaps on
    # months where that particular currency happened to have no invoices.
    currencies_seen = {currency_code for _, _, currency_code in rows}
    revenue_buckets: dict[tuple[str, str], Decimal] = {
        (_month_key(start), currency_code): Decimal("0")
        for start in month_starts
        for currency_code in currencies_seen
    }
    for created_at, total, currency_code in rows:
        key = _month_key(created_at)
        if key in invoice_counts:
            invoice_counts[key] += 1
        revenue_key = (key, currency_code)
        if revenue_key in revenue_buckets:
            revenue_buckets[revenue_key] += total

    monthly_summary = [
        MonthlySummaryPoint(month=key, invoice_count=invoice_counts[key])
        for key in sorted(invoice_counts)
    ]
    monthly_revenue_by_currency = [
        MonthlyRevenuePoint(
            month=month, currency_code=currency_code, revenue=_quantize_money(revenue)
        )
        for (month, currency_code), revenue in sorted(revenue_buckets.items())
    ]

    # --- invoice count by effective payment status, all-time ---
    status_counts = _effective_status_counts(db, organization_id)
    invoice_count_by_status = [
        PaymentStatusCountPoint(
            status=status, count=status_counts.get(status.value, 0)
        )
        for status in PaymentStatus
    ]

    # --- top customers by revenue, all-time, computed independently per
    # currency (a customer can rank differently, or not at all, in each
    # currency) ---
    top_customer_rows = db.execute(
        select(
            Customer.id,
            Customer.name,
            Invoice.currency_code,
            func.sum(Invoice.total).label("revenue"),
        )
        .join(Invoice, Invoice.customer_id == Customer.id)
        .where(Invoice.organization_id == organization_id)
        .group_by(Customer.id, Customer.name, Invoice.currency_code)
    ).all()

    # Ranked and limited in Python rather than a SQL window function
    # (ROW_NUMBER() OVER PARTITION BY), matching this function's existing
    # preference for simple, portable queries over backend-specific SQL.
    rows_by_currency: dict[str, list] = {}
    for row in top_customer_rows:
        rows_by_currency.setdefault(row.currency_code, []).append(row)

    top_customers: list[TopCustomerRevenue] = []
    for currency_code in sorted(rows_by_currency):
        ranked = sorted(
            rows_by_currency[currency_code], key=lambda r: r.revenue, reverse=True
        )
        for row in ranked[:TOP_CUSTOMERS_LIMIT]:
            top_customers.append(
                TopCustomerRevenue(
                    customer_id=row.id,
                    customer_name=row.name,
                    currency_code=currency_code,
                    revenue=_quantize_money(row.revenue),
                )
            )

    # Ranked top-N independently within each (currency, type) pair -- a
    # single "top 5 by currency" cut would let a business's many services
    # crowd out its one product entirely, leaving "top products" empty
    # even though it sold fine. Same ranked-in-Python approach as
    # top_customers above, for the same reason.
    product_revenue_rows = get_revenue_by_product(db, organization_id)
    rows_by_currency_and_type: dict[tuple[str, str], list] = {}
    for row in product_revenue_rows:
        rows_by_currency_and_type.setdefault(
            (row.currency_code, row.product_type), []
        ).append(row)

    top_products_and_services: list[TopProductRevenue] = []
    for key in sorted(rows_by_currency_and_type):
        ranked = sorted(
            rows_by_currency_and_type[key], key=lambda r: r.revenue, reverse=True
        )
        for row in ranked[:TOP_PRODUCTS_LIMIT]:
            top_products_and_services.append(
                TopProductRevenue(
                    product_id=row.product_id,
                    product_name=row.product_name,
                    product_type=row.product_type,
                    currency_code=row.currency_code,
                    revenue=_quantize_money(row.revenue),
                    invoice_count=row.invoice_count,
                )
            )

    quote_pipeline_data = get_quote_pipeline_summary(db, organization_id)
    quote_pipeline = QuotePipelineSummary(
        counts_by_status=[
            QuoteStatusCountPoint(status=status, count=quote_pipeline_data.counts_by_status.get(status.value, 0))
            for status in QuoteStatus
        ],
        acceptance_rate_percent=quote_pipeline_data.acceptance_rate_percent,
        by_currency=[
            QuoteCurrencyPipelineSummary(
                currency_code=row.currency_code,
                revenue_in_quotes=row.revenue_in_quotes,
                projected_revenue=row.projected_revenue,
                accepted_this_month=row.accepted_this_month,
                rejected_this_month=row.rejected_this_month,
                converted_this_month=row.converted_this_month,
            )
            for row in quote_pipeline_data.by_currency
        ],
    )
    quote_monthly_conversions = [
        QuoteMonthlyConversionPoint(month=point.month, converted_count=point.converted_count)
        for point in get_quote_monthly_conversions(db, organization_id, month_starts)
    ]

    team_summary_data = get_team_summary(db, organization_id)
    team_summary = TeamSummaryResponse(
        total_members=team_summary_data.total_members,
        by_role=[
            TeamRoleCount(role=row.role, count=row.count) for row in team_summary_data.by_role
        ],
        owner_count=team_summary_data.owner_count,
        pending_invitations=team_summary_data.pending_invitations,
    )

    return DashboardAnalyticsResponse(
        monthly_summary=monthly_summary,
        monthly_revenue_by_currency=monthly_revenue_by_currency,
        invoice_count_by_status=invoice_count_by_status,
        top_customers=top_customers,
        top_products_and_services=top_products_and_services,
        quote_pipeline=quote_pipeline,
        quote_monthly_conversions=quote_monthly_conversions,
        team=team_summary,
    )


@router.get("/analytics", response_model=DashboardAnalyticsResponse)
def get_dashboard_analytics(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardAnalyticsResponse:
    require_permission(current_user, organization_id, Permission.dashboard_view, db)
    return get_dashboard_analytics_data(db, organization_id)
