"""Every Pydantic request/response model for the Financial Intelligence
API. Deterministic-section schemas live here; the AI recommendation
schema (app.financial_intelligence.recommendations) and the forecast/
scenario schemas (app.financial_intelligence.forecasting) are defined in
their own modules since they carry their own, separately-reasoned
validation rules -- this file is deliberately just the deterministic
dashboard's response shapes plus the shared MetricValue building block
every one of them uses.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DataCompleteness(str, Enum):
    """How much this metric's underlying data actually supports the
    figure being shown -- distinct from forecast confidence
    (app.financial_intelligence.forecasting.ConfidenceLevel), which is
    about *predictive* reliability. This is about whether the metric
    itself rests on enough real observations to be meaningful at all
    (e.g. average_days_to_payment before any invoice has ever been
    marked paid with a real paid_at on file)."""

    complete = "complete"
    partial = "partial"
    insufficient = "insufficient"


class MetricValue(BaseModel):
    """One self-describing KPI -- every field the phase's own "every
    metric must define its source, formula, currency behavior, and
    limitations" requirement asks for. `formula_key` is a stable
    identifier into docs/financial_intelligence.md's metric dictionary,
    never a free-text formula string that could drift out of sync with
    the actual implementation."""

    id: str
    label: str
    value: Decimal | int | float | None
    currency_code: str | None = None
    period: str | None = None
    comparison_period: str | None = None
    # previous_value/trend_direction mirror app.analytics.comparison
    # .PeriodComparison's own current/previous/percentage_difference/
    # direction shape exactly -- both None together means "no previous-
    # period comparison exists for this metric" (see each KPI's own
    # `note` for why, e.g. quote_conversion_rate's low monthly sample
    # size), never a zero/flat comparison silently standing in for "not
    # computed."
    previous_value: Decimal | int | float | None = None
    percent_change: Decimal | None = None
    trend_direction: Literal["up", "down", "flat", "unknown"] | None = None
    data_completeness: DataCompleteness
    formula_key: str
    note: str | None = None


class FinancialIntelligenceCapabilities(BaseModel):
    """Echoed on every deterministic-section response so the frontend
    never has to speculatively probe a 403 to find out whether forecast/
    AI sections are worth even trying to render for this organization."""

    advanced_financial_analytics_enabled: bool
    revenue_forecasting_enabled: bool
    ai_financial_recommendations_enabled: bool
    remaining_financial_ai_reports_this_month: int | None


# --- A. Executive overview -------------------------------------------------


class ExecutiveOverviewCurrencyMetrics(BaseModel):
    currency_code: str
    invoiced_this_month: MetricValue
    collected_this_month: MetricValue
    outstanding_receivables: MetricValue
    overdue_receivables: MetricValue
    expected_collections_next_30_days: MetricValue
    average_invoice_value: MetricValue
    collection_rate: MetricValue
    overdue_rate: MetricValue


class ExecutiveOverviewResponse(BaseModel):
    generated_at: datetime
    period_start: date
    period_end: date
    by_currency: list[ExecutiveOverviewCurrencyMetrics]
    # Currency-agnostic (ratios of counts/days, not money) -- live at the
    # top level rather than duplicated per currency.
    quote_conversion_rate: MetricValue
    average_days_to_payment: MetricValue
    capabilities: FinancialIntelligenceCapabilities


# --- B. Revenue trends -------------------------------------------------


class RevenueTrendPoint(BaseModel):
    period: str
    currency_code: str
    invoiced: Decimal
    collected: Decimal
    invoice_count: int


class RevenueTrendsResponse(BaseModel):
    generated_at: datetime
    granularity: Literal["monthly"]
    points: list[RevenueTrendPoint]
    month_over_month_change_percent: dict[str, Decimal | None]
    year_over_year_change_percent: dict[str, Decimal | None]
    rolling_3_month_average: dict[str, Decimal]
    rolling_6_month_average: dict[str, Decimal]
    data_completeness: DataCompleteness


# --- C. Accounts receivable aging -------------------------------------------------

AgingBucketName = Literal[
    "not_yet_due", "overdue_1_30", "overdue_31_60", "overdue_61_90", "overdue_90_plus"
]


class AgingBucket(BaseModel):
    bucket: AgingBucketName
    currency_code: str
    amount: Decimal
    invoice_count: int
    percent_of_total: Decimal | None


class TopOverdueCustomer(BaseModel):
    customer_id: str
    customer_name: str
    currency_code: str
    overdue_total: Decimal
    overdue_invoice_count: int
    oldest_overdue_days: int


class ReceivablesAgingResponse(BaseModel):
    generated_at: datetime
    as_of_date: date
    buckets: list[AgingBucket]
    top_overdue_customers: list[TopOverdueCustomer]
    invoices_missing_due_date: int


# --- D. Customers -------------------------------------------------


class CustomerRevenueEntry(BaseModel):
    customer_id: str
    customer_name: str
    currency_code: str
    revenue: Decimal
    invoice_count: int


class CustomerOutstandingEntry(BaseModel):
    customer_id: str
    customer_name: str
    currency_code: str
    outstanding_total: Decimal


class CustomerConcentration(BaseModel):
    currency_code: str
    top_customer_share_percent: Decimal | None
    top_3_customers_share_percent: Decimal | None
    data_completeness: DataCompleteness


class RepeatCustomerContribution(BaseModel):
    currency_code: str
    repeat_customer_revenue_share_percent: Decimal | None
    repeat_customer_count: int
    total_customer_count: int


class AtRiskCustomer(BaseModel):
    """`rule` names exactly which transparent, deterministic rule fired
    (never an opaque AI judgment) -- see docs/financial_intelligence.md's
    anomaly/at-risk rules section."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str
    customer_name: str
    currency_code: str | None
    rule: Literal["repeated_overdue_invoices", "overdue_far_beyond_average_delay"]
    evidence: str
    open_invoice_count: int
    overdue_total: Decimal | None


class CustomersSectionResponse(BaseModel):
    generated_at: datetime
    period_start: date
    period_end: date
    top_by_revenue: list[CustomerRevenueEntry]
    top_by_outstanding: list[CustomerOutstandingEntry]
    most_overdue: list[TopOverdueCustomer]
    concentration: list[CustomerConcentration]
    repeat_contribution: list[RepeatCustomerContribution]
    customer_growth_count: int
    at_risk: list[AtRiskCustomer]


# --- E. Products and services -------------------------------------------------


class ProductRevenueEntry(BaseModel):
    product_id: str
    product_name: str
    product_type: str
    currency_code: str
    revenue: Decimal
    quantity: Decimal
    invoice_count: int
    average_sale_value: Decimal


class ProductTrend(BaseModel):
    product_id: str
    product_name: str
    currency_code: str
    direction: Literal["increasing", "decreasing", "flat", "insufficient_data"]
    months_observed: int


class ProductConcentration(BaseModel):
    currency_code: str
    top_product_share_percent: Decimal | None


class ProductsSectionResponse(BaseModel):
    generated_at: datetime
    period_start: date
    period_end: date
    by_revenue: list[ProductRevenueEntry]
    trends: list[ProductTrend]
    concentration: list[ProductConcentration]
    declining: list[ProductTrend]


# --- F. Quotes funnel -------------------------------------------------


class QuoteFunnelCounts(BaseModel):
    created: int
    sent: int
    accepted: int
    rejected: int
    expired: int
    converted: int


class QuoteFunnelCurrencyValue(BaseModel):
    currency_code: str
    quoted_value: Decimal
    converted_value: Decimal


class QuotesSectionResponse(BaseModel):
    generated_at: datetime
    counts: QuoteFunnelCounts
    conversion_rate_percent: Decimal | None
    average_time_to_acceptance_days: MetricValue
    by_currency: list[QuoteFunnelCurrencyValue]


# --- G. Cash-flow (receivables) calendar -------------------------------------------------

# Deliberately never called "profit"/"net cash flow" anywhere in this
# schema, its field names, or its serialized values -- this app tracks no
# expenses, so there is no P&L concept it could honestly compute. See
# docs/financial_intelligence.md.
CASHFLOW_DISCLAIMER = (
    "This is a receivables (money owed to you) forecast based on invoice "
    "due dates, not a profit-and-loss or net cash-flow statement -- "
    "expenses are not tracked in this application."
)


class CollectionsCalendarPoint(BaseModel):
    period_start: date
    period_end: date
    currency_code: str
    known_amount: Decimal
    invoice_count: int


class CashflowCalendarResponse(BaseModel):
    generated_at: datetime
    as_of_date: date
    granularity: Literal["day", "week", "month"]
    horizon_days: int
    points: list[CollectionsCalendarPoint]
    disclaimer: str = CASHFLOW_DISCLAIMER
