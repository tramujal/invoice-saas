"""Deterministic executive-overview / customers / products / quotes-
funnel assembly for the Financial Intelligence module.

Composes app.analytics.service.AnalyticsService, app.product_analytics,
and app.quote_analytics wherever they already compute the figure needed
-- the only genuinely new math in this file is: collection/overdue rate,
average-days-to-payment, customer concentration/repeat-contribution/at-
risk rules, and product trend/concentration/decline detection.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import AnalyticsService
from app.analytics.time_windows import TimeWindowKind, resolve_time_window, trailing_month_starts
from app.billing.capabilities import (
    can_use_advanced_financial_analytics,
    can_use_ai_financial_recommendations,
    can_use_revenue_forecasting,
    get_organization_capabilities,
    remaining_financial_ai_reports_quota,
)
from app.analytics.comparison import compare_periods
from app.analytics.primitives import growth_percent
from app.financial_intelligence import cashflow, queries
from app.financial_intelligence.schemas import (
    AgingBucket,
    AtRiskCustomer,
    CashflowCalendarResponse,
    CollectionsCalendarPoint,
    CustomerConcentration,
    CustomerOutstandingEntry,
    CustomerRevenueEntry,
    CustomersSectionResponse,
    DataCompleteness,
    ExecutiveOverviewCurrencyMetrics,
    ExecutiveOverviewResponse,
    FinancialIntelligenceCapabilities,
    MetricValue,
    ProductConcentration,
    ProductRevenueEntry,
    ProductsSectionResponse,
    ProductTrend,
    QuoteFunnelCounts,
    QuoteFunnelCurrencyValue,
    QuotesSectionResponse,
    ReceivablesAgingResponse,
    RepeatCustomerContribution,
    RevenueTrendPoint,
    RevenueTrendsResponse,
    TopOverdueCustomer,
)
from app.models import Organization, Quote
from app.org_time import get_organization_today
from app.product_analytics import get_revenue_by_product
from app.quote_analytics import get_quote_pipeline_summary
from app.quote_status import QuoteStatus

TOP_CUSTOMERS_LIMIT = 5
TOP_PRODUCTS_LIMIT = 10
TOP_OVERDUE_CUSTOMERS_LIMIT = 10
PRODUCT_TREND_MONTHS = 6
MIN_PRODUCT_TREND_OBSERVATIONS = 3
MIN_PAYMENT_DELAY_OBSERVATIONS = cashflow.MIN_PAYMENT_DELAY_OBSERVATIONS
EXPECTED_COLLECTIONS_HORIZON_DAYS = 30
# 13, not 12: a genuine year-over-year comparison for the latest month
# needs one additional trailing month as its own baseline (see
# build_revenue_trends_section) -- 12 months of *displayed* points plus
# the one extra used only to compute the first displayed point's own MoM.
REVENUE_TREND_MONTHS = 13
CASHFLOW_CALENDAR_HORIZON_DAYS = 30
CASHFLOW_CALENDAR_GRANULARITY = "week"

# At-risk customer rules -- transparent, named, deterministic. A customer
# is flagged if EITHER fires; both are reported with their own evidence
# string (see AtRiskCustomer.rule), never a single opaque "at risk" flag.
AT_RISK_MIN_OPEN_OVERDUE_INVOICES = 3
AT_RISK_DELAY_MULTIPLIER = Decimal("2")

MONEY_QUANTIZE = Decimal("0.01")
PERCENT_QUANTIZE = Decimal("0.01")


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator is None or denominator <= 0:
        return None
    return (numerator / denominator * 100).quantize(PERCENT_QUANTIZE)


def build_capabilities_block(db: Session, organization_id: str) -> FinancialIntelligenceCapabilities:
    caps = get_organization_capabilities(db, organization_id)
    return FinancialIntelligenceCapabilities(
        advanced_financial_analytics_enabled=can_use_advanced_financial_analytics(caps),
        revenue_forecasting_enabled=can_use_revenue_forecasting(caps),
        ai_financial_recommendations_enabled=can_use_ai_financial_recommendations(caps),
        remaining_financial_ai_reports_this_month=remaining_financial_ai_reports_quota(caps),
    )


# --- A. Executive overview -------------------------------------------------


def _comparable_metric(
    *,
    id: str,
    label: str,
    current: Decimal,
    previous: Decimal,
    currency_code: str | None,
    period: str,
    comparison_period: str,
    formula_key: str,
    data_completeness: DataCompleteness = DataCompleteness.complete,
    note: str | None = None,
) -> MetricValue:
    """Builds one KPI card with a genuine previous-period comparison,
    reusing app.analytics.comparison.compare_periods so every KPI's
    trend classification (up/down/flat/unknown) is computed by the exact
    same rule the rest of the app's trend indicators already use."""
    comparison = compare_periods(current, previous)
    return MetricValue(
        id=id,
        label=label,
        value=comparison.current,
        currency_code=currency_code,
        period=period,
        comparison_period=comparison_period,
        previous_value=comparison.previous,
        percent_change=comparison.percentage_difference,
        trend_direction=comparison.direction.value,
        data_completeness=data_completeness,
        formula_key=formula_key,
        note=note,
    )


def build_executive_overview(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ExecutiveOverviewResponse:
    now = now or datetime.now(timezone.utc)
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    this_month = resolve_time_window(TimeWindowKind.current_month, organization=organization, now=now)
    previous_month_end = this_month.start.date() - timedelta(days=1)

    analytics = AnalyticsService(db=db, organization_id=organization_id)
    avg_invoice_value = analytics.average_invoice_value(window=this_month)
    avg_invoice_value_prev = analytics.average_invoice_value(
        window=resolve_time_window(TimeWindowKind.previous_month, organization=organization, now=now)
    )

    # Two trailing months (current + previous) of real invoiced/collected
    # totals -- the same query the Revenue trends section uses, reused
    # here so "revenue this month"/"collected this month" and their
    # comparisons are computed by the identical method, never a second,
    # slightly-different one.
    month_starts = trailing_month_starts(2, now=now)
    monthly_rows = queries.get_monthly_revenue_series(db, organization_id, month_starts)
    month_keys = [start.strftime("%Y-%m") for start in month_starts]
    current_month_key, previous_month_key = month_keys[-1], month_keys[0]
    monthly_by_currency: dict[str, dict[str, queries.MonthlyRevenueRow]] = {}
    for row in monthly_rows:
        monthly_by_currency.setdefault(row.currency_code, {})[row.month] = row

    # Outstanding/overdue as of now vs. as of the end of the previous
    # month -- both computed by the SAME conservative reconstruction (see
    # queries.get_receivables_snapshot), so the comparison is
    # methodologically consistent even though the absolute numbers are an
    # approximation for any currently-paid invoice with no recorded
    # paid_at (see that function's own docstring, and
    # docs/financial_dashboard.md's limitations section).
    snapshot_now = queries.get_receivables_snapshot(db, organization_id, as_of=today_local)
    snapshot_prev = queries.get_receivables_snapshot(db, organization_id, as_of=previous_month_end)

    calendar = cashflow.build_collections_calendar(
        db, organization_id, today_local=today_local, horizon_days=EXPECTED_COLLECTIONS_HORIZON_DAYS,
        granularity="month",
    )
    expected_30d: dict[str, Decimal] = {}
    for point in calendar:
        expected_30d[point.currency_code] = expected_30d.get(point.currency_code, Decimal("0")) + point.known_amount

    currencies = sorted(
        set(monthly_by_currency) | set(avg_invoice_value) | set(expected_30d) | set(snapshot_now)
    )

    by_currency: list[ExecutiveOverviewCurrencyMetrics] = []
    for code in currencies:
        current_row = monthly_by_currency.get(code, {}).get(current_month_key)
        previous_row = monthly_by_currency.get(code, {}).get(previous_month_key)
        invoiced_now = current_row.invoiced if current_row else Decimal("0")
        invoiced_prev = previous_row.invoiced if previous_row else Decimal("0")
        collected_now = current_row.collected if current_row else Decimal("0")
        collected_prev = previous_row.collected if previous_row else Decimal("0")

        outstanding_now, overdue_now = snapshot_now.get(code, (Decimal("0"), Decimal("0")))
        outstanding_prev, overdue_prev = snapshot_prev.get(code, (Decimal("0"), Decimal("0")))

        rate_now = _pct(collected_now, invoiced_now)
        rate_prev = _pct(collected_prev, invoiced_prev)
        overdue_rate = _pct(overdue_now, outstanding_now)
        has_avg_invoice = code in avg_invoice_value

        by_currency.append(
            ExecutiveOverviewCurrencyMetrics(
                currency_code=code,
                invoiced_this_month=_comparable_metric(
                    id="invoiced_this_month",
                    label="Invoiced revenue this month",
                    current=invoiced_now,
                    previous=invoiced_prev,
                    currency_code=code,
                    period="current_month",
                    comparison_period="previous_month",
                    formula_key="invoiced_revenue",
                ),
                collected_this_month=_comparable_metric(
                    id="collected_this_month",
                    label="Collected revenue this month",
                    current=collected_now,
                    previous=collected_prev,
                    currency_code=code,
                    period="current_month",
                    comparison_period="previous_month",
                    formula_key="collected_revenue",
                ),
                outstanding_receivables=_comparable_metric(
                    id="outstanding_receivables",
                    label="Outstanding receivables",
                    current=outstanding_now,
                    previous=outstanding_prev,
                    currency_code=code,
                    period="as_of_today",
                    comparison_period="as_of_previous_month_end",
                    formula_key="outstanding_receivables",
                    note=(
                        "A point-in-time balance, reconstructed conservatively for "
                        "the prior date -- see docs/financial_dashboard.md."
                    ),
                ),
                overdue_receivables=_comparable_metric(
                    id="overdue_receivables",
                    label="Overdue receivables",
                    current=overdue_now,
                    previous=overdue_prev,
                    currency_code=code,
                    period="as_of_today",
                    comparison_period="as_of_previous_month_end",
                    formula_key="overdue_receivables",
                    note=(
                        "A point-in-time balance, reconstructed conservatively for "
                        "the prior date -- see docs/financial_dashboard.md."
                    ),
                ),
                expected_collections_next_30_days=MetricValue(
                    id="expected_collections_next_30_days",
                    label="Expected collections, next 30 days",
                    value=expected_30d.get(code, Decimal("0")),
                    currency_code=code,
                    period="next_30_days",
                    data_completeness=DataCompleteness.partial,
                    formula_key="expected_collections_30d",
                    note=(
                        "Based on currently-open invoices' due dates and this "
                        "organization's own historical payment-delay behavior for "
                        "overdue invoices -- not a guarantee. No previous-period "
                        "comparison: this is a forward-looking projection, not a "
                        "value that itself had a 'previous' instance."
                    ),
                ),
                average_invoice_value=_comparable_metric(
                    id="average_invoice_value",
                    label="Average invoice value",
                    current=avg_invoice_value.get(code) or Decimal("0"),
                    previous=avg_invoice_value_prev.get(code) or Decimal("0"),
                    currency_code=code,
                    period="current_month",
                    comparison_period="previous_month",
                    formula_key="average_invoice_value",
                    data_completeness=(
                        DataCompleteness.complete if has_avg_invoice else DataCompleteness.insufficient
                    ),
                ),
                collection_rate=_comparable_metric(
                    id="collection_rate",
                    label="Collection rate",
                    current=rate_now if rate_now is not None else Decimal("0"),
                    previous=rate_prev if rate_prev is not None else Decimal("0"),
                    currency_code=code,
                    period="current_month",
                    comparison_period="previous_month",
                    formula_key="collection_rate",
                    data_completeness=(
                        DataCompleteness.complete if invoiced_now > 0 else DataCompleteness.insufficient
                    ),
                    note="This month's collections as a percentage of this month's invoiced revenue.",
                ),
                overdue_rate=MetricValue(
                    id="overdue_rate",
                    label="Overdue rate",
                    value=overdue_rate,
                    currency_code=code,
                    period="as_of_today",
                    data_completeness=(
                        DataCompleteness.complete if outstanding_now > 0 else DataCompleteness.insufficient
                    ),
                    formula_key="overdue_rate",
                ),
            )
        )

    quote_rate = analytics.quote_acceptance_rate()
    delay_stats = cashflow.compute_payment_delay_stats(db, organization_id)

    return ExecutiveOverviewResponse(
        generated_at=now,
        period_start=this_month.start.date(),
        period_end=this_month.end.date(),
        by_currency=by_currency,
        quote_conversion_rate=MetricValue(
            id="quote_conversion_rate",
            label="Quote conversion rate",
            value=Decimal(str(quote_rate)).quantize(PERCENT_QUANTIZE) if quote_rate is not None else None,
            period="all_time",
            data_completeness=(
                DataCompleteness.complete if quote_rate is not None else DataCompleteness.insufficient
            ),
            formula_key="quote_conversion_rate",
            note=(
                "Shown as an all-time rate, not month-over-month: a typical "
                "organization sends too few quotes in any single month for a "
                "monthly conversion-rate comparison to be meaningful rather "
                "than noise."
            ),
        ),
        average_days_to_payment=MetricValue(
            id="average_days_to_payment",
            label="Average days to payment",
            value=delay_stats.average_days,
            period="all_time",
            data_completeness=(
                DataCompleteness.complete if delay_stats.available else DataCompleteness.insufficient
            ),
            formula_key="average_days_to_payment",
            note=(
                None
                if delay_stats.available
                else (
                    "Not enough invoices have been marked paid with a recorded "
                    "payment date yet (needs at least "
                    f"{MIN_PAYMENT_DELAY_OBSERVATIONS})."
                )
            ),
        ),
        capabilities=build_capabilities_block(db, organization_id),
    )


# --- D. Customers -------------------------------------------------


def build_customers_section(
    db: Session, organization_id: str, *, now: datetime | None = None, limit: int = TOP_CUSTOMERS_LIMIT
) -> CustomersSectionResponse:
    now = now or datetime.now(timezone.utc)
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    this_month = resolve_time_window(TimeWindowKind.current_month, organization=organization, now=now)

    revenue_rows = queries.get_customer_revenue_all(db, organization_id)
    overdue_rows = queries.get_customer_overdue_totals(db, organization_id, today_local=today_local)
    open_counts = queries.get_customer_open_invoice_counts(db, organization_id)
    org_delay = cashflow.compute_payment_delay_stats(db, organization_id)

    by_currency_revenue: dict[str, list] = {}
    totals_by_currency: dict[str, Decimal] = {}
    for row in revenue_rows:
        by_currency_revenue.setdefault(row.currency_code, []).append(row)
        totals_by_currency[row.currency_code] = totals_by_currency.get(row.currency_code, Decimal("0")) + row.revenue

    top_by_revenue: list[CustomerRevenueEntry] = []
    top_by_outstanding: list[CustomerOutstandingEntry] = []
    concentration: list[CustomerConcentration] = []
    repeat_contribution: list[RepeatCustomerContribution] = []

    for code in sorted(by_currency_revenue):
        ranked = sorted(by_currency_revenue[code], key=lambda r: r.revenue, reverse=True)
        for row in ranked[:limit]:
            top_by_revenue.append(
                CustomerRevenueEntry(
                    customer_id=row.customer_id,
                    customer_name=row.customer_name,
                    currency_code=code,
                    revenue=row.revenue.quantize(MONEY_QUANTIZE),
                    invoice_count=row.invoice_count,
                )
            )

        total = totals_by_currency[code]
        top_1_share = _pct(ranked[0].revenue, total) if ranked else None
        top_3_total = sum((r.revenue for r in ranked[:3]), Decimal("0"))
        top_3_share = _pct(top_3_total, total) if ranked else None
        concentration.append(
            CustomerConcentration(
                currency_code=code,
                top_customer_share_percent=top_1_share,
                top_3_customers_share_percent=top_3_share,
                data_completeness=(
                    DataCompleteness.complete if len(ranked) >= 3 else DataCompleteness.partial
                ),
            )
        )

        repeat = [r for r in by_currency_revenue[code] if r.invoice_count >= 2]
        repeat_revenue = sum((r.revenue for r in repeat), Decimal("0"))
        repeat_contribution.append(
            RepeatCustomerContribution(
                currency_code=code,
                repeat_customer_revenue_share_percent=_pct(repeat_revenue, total),
                repeat_customer_count=len(repeat),
                total_customer_count=len(by_currency_revenue[code]),
            )
        )

    by_currency_overdue: dict[str, list] = {}
    for row in overdue_rows:
        by_currency_overdue.setdefault(row.currency_code, []).append(row)
    for code in sorted(by_currency_overdue):
        ranked = sorted(by_currency_overdue[code], key=lambda r: r.overdue_total, reverse=True)
        for row in ranked[:limit]:
            top_by_outstanding.append(
                CustomerOutstandingEntry(
                    customer_id=row.customer_id,
                    customer_name=row.customer_name,
                    currency_code=code,
                    outstanding_total=row.overdue_total.quantize(MONEY_QUANTIZE),
                )
            )

    most_overdue = sorted(overdue_rows, key=lambda r: r.overdue_total, reverse=True)[:limit]
    most_overdue_entries = [
        TopOverdueCustomer(
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            currency_code=row.currency_code,
            overdue_total=row.overdue_total.quantize(MONEY_QUANTIZE),
            overdue_invoice_count=row.overdue_invoice_count,
            oldest_overdue_days=(today_local - row.oldest_due_date).days,
        )
        for row in most_overdue
    ]

    at_risk: list[AtRiskCustomer] = []
    for row in overdue_rows:
        open_count = open_counts.get(row.customer_id, 0)
        if open_count >= AT_RISK_MIN_OPEN_OVERDUE_INVOICES:
            at_risk.append(
                AtRiskCustomer(
                    customer_id=row.customer_id,
                    customer_name=row.customer_name,
                    currency_code=row.currency_code,
                    rule="repeated_overdue_invoices",
                    evidence=f"{open_count} unpaid invoices currently outstanding.",
                    open_invoice_count=open_count,
                    overdue_total=row.overdue_total.quantize(MONEY_QUANTIZE),
                )
            )
        elif org_delay.available and org_delay.average_days is not None:
            oldest_overdue_days = (today_local - row.oldest_due_date).days
            threshold = org_delay.average_days * AT_RISK_DELAY_MULTIPLIER
            if Decimal(oldest_overdue_days) > threshold:
                at_risk.append(
                    AtRiskCustomer(
                        customer_id=row.customer_id,
                        customer_name=row.customer_name,
                        currency_code=row.currency_code,
                        rule="overdue_far_beyond_average_delay",
                        evidence=(
                            f"Oldest overdue invoice is {oldest_overdue_days} days late -- "
                            f"more than {AT_RISK_DELAY_MULTIPLIER}x this organization's own "
                            f"average payment delay ({org_delay.average_days} days)."
                        ),
                        open_invoice_count=open_count,
                        overdue_total=row.overdue_total.quantize(MONEY_QUANTIZE),
                    )
                )
    at_risk.sort(key=lambda c: c.overdue_total or Decimal("0"), reverse=True)

    growth_count = AnalyticsService(db=db, organization_id=organization_id).customer_growth(this_month)

    return CustomersSectionResponse(
        generated_at=now,
        period_start=this_month.start.date(),
        period_end=this_month.end.date(),
        top_by_revenue=top_by_revenue,
        top_by_outstanding=top_by_outstanding,
        most_overdue=most_overdue_entries,
        concentration=concentration,
        repeat_contribution=repeat_contribution,
        customer_growth_count=growth_count,
        at_risk=at_risk,
    )


# --- E. Products and services -------------------------------------------------


def build_products_section(
    db: Session, organization_id: str, *, now: datetime | None = None, limit: int = TOP_PRODUCTS_LIMIT
) -> ProductsSectionResponse:
    now = now or datetime.now(timezone.utc)
    organization = db.get(Organization, organization_id)
    this_month = resolve_time_window(TimeWindowKind.current_month, organization=organization, now=now)

    revenue_rows = get_revenue_by_product(db, organization_id)
    quantities = queries.get_product_quantity_sold(db, organization_id)

    by_currency: dict[str, list] = {}
    totals_by_currency: dict[str, Decimal] = {}
    for row in revenue_rows:
        by_currency.setdefault(row.currency_code, []).append(row)
        totals_by_currency[row.currency_code] = totals_by_currency.get(row.currency_code, Decimal("0")) + row.revenue

    by_revenue: list[ProductRevenueEntry] = []
    concentration: list[ProductConcentration] = []
    for code in sorted(by_currency):
        ranked = sorted(by_currency[code], key=lambda r: r.revenue, reverse=True)
        for row in ranked[:limit]:
            qty = quantities.get((row.product_id, code), Decimal("0"))
            avg_sale = (row.revenue / row.invoice_count).quantize(MONEY_QUANTIZE) if row.invoice_count else Decimal("0")
            by_revenue.append(
                ProductRevenueEntry(
                    product_id=row.product_id,
                    product_name=row.product_name,
                    product_type=row.product_type,
                    currency_code=code,
                    revenue=row.revenue.quantize(MONEY_QUANTIZE),
                    quantity=qty,
                    invoice_count=row.invoice_count,
                    average_sale_value=avg_sale,
                )
            )
        total = totals_by_currency[code]
        top_share = _pct(ranked[0].revenue, total) if ranked else None
        concentration.append(ProductConcentration(currency_code=code, top_product_share_percent=top_share))

    month_starts = trailing_month_starts(PRODUCT_TREND_MONTHS, now=now)
    monthly_rows = queries.get_product_monthly_revenue(db, organization_id, month_starts)
    by_product_month: dict[tuple[str, str], dict[str, Decimal]] = {}
    names_by_id: dict[str, str] = {}
    for row in monthly_rows:
        names_by_id[row.product_id] = row.product_name
        key = (row.product_id, row.currency_code)
        by_product_month.setdefault(key, {})[row.month] = row.revenue

    trends: list[ProductTrend] = []
    month_keys = [start.strftime("%Y-%m") for start in month_starts]
    for (product_id, currency_code), series_by_month in by_product_month.items():
        series = [series_by_month.get(m, Decimal("0")) for m in month_keys]
        observed = sum(1 for v in series if v > 0)
        if observed < MIN_PRODUCT_TREND_OBSERVATIONS:
            direction = "insufficient_data"
        else:
            half = len(series) // 2
            first_half_avg = sum(series[:half], Decimal("0")) / Decimal(max(half, 1))
            second_half_avg = sum(series[half:], Decimal("0")) / Decimal(max(len(series) - half, 1))
            if second_half_avg > first_half_avg * Decimal("1.1"):
                direction = "increasing"
            elif second_half_avg < first_half_avg * Decimal("0.9"):
                direction = "decreasing"
            else:
                direction = "flat"
        trends.append(
            ProductTrend(
                product_id=product_id,
                product_name=names_by_id[product_id],
                currency_code=currency_code,
                direction=direction,
                months_observed=observed,
            )
        )
    trends.sort(key=lambda t: (t.product_name, t.currency_code))
    declining = [t for t in trends if t.direction == "decreasing"]

    return ProductsSectionResponse(
        generated_at=now,
        period_start=this_month.start.date(),
        period_end=this_month.end.date(),
        by_revenue=by_revenue,
        trends=trends,
        concentration=concentration,
        declining=declining,
    )


# --- F. Quotes funnel -------------------------------------------------


def build_quotes_section(db: Session, organization_id: str, *, now: datetime | None = None) -> QuotesSectionResponse:
    now = now or datetime.now(timezone.utc)
    analytics = AnalyticsService(db=db, organization_id=organization_id)
    pipeline = analytics.quote_acceptance_rate()
    pipeline_data = get_quote_pipeline_summary(db, organization_id)
    counts_by_status = pipeline_data.counts_by_status
    created = sum(counts_by_status.values())

    value_rows = queries.get_quote_value_by_currency(db, organization_id)
    by_currency = [
        QuoteFunnelCurrencyValue(
            currency_code=row.currency_code,
            quoted_value=row.quoted_value.quantize(MONEY_QUANTIZE),
            converted_value=row.converted_value.quantize(MONEY_QUANTIZE),
        )
        for row in value_rows
    ]

    avg_time_days = _average_time_to_acceptance_days(db, organization_id)

    return QuotesSectionResponse(
        generated_at=now,
        counts=QuoteFunnelCounts(
            created=created,
            sent=counts_by_status.get(QuoteStatus.sent.value, 0),
            accepted=counts_by_status.get(QuoteStatus.accepted.value, 0),
            rejected=counts_by_status.get(QuoteStatus.rejected.value, 0),
            expired=counts_by_status.get(QuoteStatus.expired.value, 0),
            converted=counts_by_status.get(QuoteStatus.converted.value, 0),
        ),
        conversion_rate_percent=(
            Decimal(str(pipeline)).quantize(PERCENT_QUANTIZE) if pipeline is not None else None
        ),
        average_time_to_acceptance_days=avg_time_days,
        by_currency=by_currency,
    )


def _average_time_to_acceptance_days(db: Session, organization_id: str) -> MetricValue:
    """updated_at - issue_date for effectively-accepted quotes -- an
    APPROXIMATION, documented explicitly (see class docstring in
    app.quote_analytics): Quote has no dedicated accepted_at column,
    only the generic updated_at every status-changing write touches."""
    rows = db.execute(
        select(Quote.issue_date, Quote.updated_at).where(
            Quote.organization_id == organization_id, Quote.status == QuoteStatus.accepted.value
        )
    ).all()
    durations = []
    for issue_date, updated_at in rows:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        durations.append((updated_at.date() - issue_date).days)

    if not durations:
        return MetricValue(
            id="average_time_to_acceptance_days",
            label="Average time to acceptance",
            value=None,
            period="all_time",
            data_completeness=DataCompleteness.insufficient,
            formula_key="average_time_to_acceptance",
            note="No accepted quotes yet.",
        )
    average = Decimal(sum(durations)) / Decimal(len(durations))
    return MetricValue(
        id="average_time_to_acceptance_days",
        label="Average time to acceptance",
        value=average.quantize(Decimal("0.1")),
        period="all_time",
        data_completeness=DataCompleteness.partial,
        formula_key="average_time_to_acceptance",
        note=(
            "Approximate: quotes don't record a dedicated acceptance timestamp, "
            "so this uses the quote's last-modified date instead."
        ),
    )


# --- B. Revenue trends -------------------------------------------------


def build_revenue_trends_section(
    db: Session, organization_id: str, *, now: datetime | None = None, months: int = REVENUE_TREND_MONTHS
) -> RevenueTrendsResponse:
    """Monthly invoiced/collected/invoice-count series, rolling 3- and
    6-month averages, and month-over-month/year-over-year change, all per
    currency. Fetches one extra leading month beyond what's actually
    displayed (see REVENUE_TREND_MONTHS) purely so the earliest displayed
    point still has a real month-over-month baseline; year-over-year
    compares the latest displayed month against that same extra month,
    12 months earlier."""
    now = now or datetime.now(timezone.utc)
    month_starts = trailing_month_starts(max(months, 2), now=now)
    rows = queries.get_monthly_revenue_series(db, organization_id, month_starts)

    month_keys = [start.strftime("%Y-%m") for start in month_starts]
    by_currency_month: dict[str, dict[str, queries.MonthlyRevenueRow]] = {}
    for row in rows:
        by_currency_month.setdefault(row.currency_code, {})[row.month] = row

    currencies = sorted(by_currency_month)
    displayed_months = month_keys[1:]  # drop the extra leading baseline month

    points: list[RevenueTrendPoint] = []
    month_over_month: dict[str, Decimal | None] = {}
    year_over_year: dict[str, Decimal | None] = {}
    rolling_3: dict[str, Decimal] = {}
    rolling_6: dict[str, Decimal] = {}

    for code in currencies:
        series_by_month = by_currency_month[code]

        def invoiced_at(month: str) -> Decimal:
            row = series_by_month.get(month)
            return row.invoiced if row else Decimal("0")

        for month in displayed_months:
            row = series_by_month.get(month)
            points.append(
                RevenueTrendPoint(
                    period=month,
                    currency_code=code,
                    invoiced=(row.invoiced if row else Decimal("0")).quantize(MONEY_QUANTIZE),
                    collected=(row.collected if row else Decimal("0")).quantize(MONEY_QUANTIZE),
                    invoice_count=row.invoice_count if row else 0,
                )
            )

        latest = displayed_months[-1]
        month_over_month[code] = (
            growth_percent(invoiced_at(latest), invoiced_at(displayed_months[-2]))
            if len(displayed_months) >= 2
            else None
        )
        # Baseline (month_keys[0]) is exactly 12 months before the latest
        # displayed month -- growth_percent already returns None on a
        # zero/absent baseline, which is exactly "no data that far back."
        year_over_year[code] = growth_percent(invoiced_at(latest), invoiced_at(month_keys[0]))

        recent_3 = [invoiced_at(m) for m in displayed_months[-3:]]
        recent_6 = [invoiced_at(m) for m in displayed_months[-6:]]
        rolling_3[code] = (sum(recent_3, Decimal("0")) / Decimal(len(recent_3))).quantize(MONEY_QUANTIZE)
        rolling_6[code] = (sum(recent_6, Decimal("0")) / Decimal(len(recent_6))).quantize(MONEY_QUANTIZE)

    return RevenueTrendsResponse(
        generated_at=now,
        granularity="monthly",
        points=points,
        month_over_month_change_percent=month_over_month,
        year_over_year_change_percent=year_over_year,
        rolling_3_month_average=rolling_3,
        rolling_6_month_average=rolling_6,
        data_completeness=(DataCompleteness.complete if rows else DataCompleteness.insufficient),
    )


# --- C. Accounts receivable aging -------------------------------------------------


def build_receivables_section(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ReceivablesAgingResponse:
    now = now or datetime.now(timezone.utc)
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)

    aging = cashflow.compute_aging_buckets(db, organization_id, today_local=today_local)
    overdue_rows = queries.get_customer_overdue_totals(db, organization_id, today_local=today_local)
    top_overdue = sorted(overdue_rows, key=lambda r: r.overdue_total, reverse=True)[:TOP_OVERDUE_CUSTOMERS_LIMIT]

    return ReceivablesAgingResponse(
        generated_at=now,
        as_of_date=today_local,
        buckets=[
            AgingBucket(
                bucket=b.bucket,
                currency_code=b.currency_code,
                amount=b.amount,
                invoice_count=b.invoice_count,
                percent_of_total=b.percent_of_total,
            )
            for b in aging.buckets
        ],
        top_overdue_customers=[
            TopOverdueCustomer(
                customer_id=row.customer_id,
                customer_name=row.customer_name,
                currency_code=row.currency_code,
                overdue_total=row.overdue_total.quantize(MONEY_QUANTIZE),
                overdue_invoice_count=row.overdue_invoice_count,
                oldest_overdue_days=(today_local - row.oldest_due_date).days,
            )
            for row in top_overdue
        ],
        invoices_missing_due_date=aging.invoices_missing_due_date,
    )


# --- G. Cash-flow (receivables) calendar -------------------------------------------------


def build_cashflow_calendar_section(
    db: Session,
    organization_id: str,
    *,
    now: datetime | None = None,
    horizon_days: int = CASHFLOW_CALENDAR_HORIZON_DAYS,
    granularity: str = CASHFLOW_CALENDAR_GRANULARITY,
) -> CashflowCalendarResponse:
    now = now or datetime.now(timezone.utc)
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)

    points = cashflow.build_collections_calendar(
        db, organization_id, today_local=today_local, horizon_days=horizon_days, granularity=granularity
    )

    return CashflowCalendarResponse(
        generated_at=now,
        as_of_date=today_local,
        granularity=granularity,
        horizon_days=horizon_days,
        points=[
            CollectionsCalendarPoint(
                period_start=p.period_start,
                period_end=p.period_end,
                currency_code=p.currency_code,
                known_amount=p.known_amount,
                invoice_count=p.invoice_count,
            )
            for p in points
        ],
    )
