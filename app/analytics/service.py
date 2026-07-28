"""AnalyticsService -- the single entry point every router, the AI
insights engine, and the AI assistant's context builder go through for
business metrics.

Constructed per-request with (db, organization_id): a thin, stateless
facade over the calculators in app.analytics.calculators, never business
logic of its own. Every KPI method here is a one-line delegation; the two
larger methods at the bottom (dashboard_summary/dashboard_analytics)
assemble several calculator calls into the existing DashboardResponse/
DashboardAnalyticsResponse shape -- the exact same computation that used
to live directly inside app.routers.dashboard's route handlers (as
get_dashboard_summary/get_dashboard_analytics_data), relocated here so
those route handlers become pure orchestration: parse the request, call
this service, return its result. If a method here ever needs real
conditional logic beyond assembly, that logic belongs in a calculator,
not in this class, so it stays testable without going through a Session
or an organization_id at all.

Tenant scoping is structural, not a discipline every method has to
remember: organization_id is bound once, in __init__, and every delegated
calculator call receives it -- there is no method on this class that lets
a caller accidentally query a different organization's data than the one
this instance was constructed for.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.analytics.calculators import customers as customers_calc
from app.analytics.calculators import invoices as invoices_calc
from app.analytics.calculators import payments as payments_calc
from app.analytics.calculators import products as products_calc
from app.analytics.calculators import quotes as quotes_calc
from app.analytics.calculators import revenue as revenue_calc
from app.analytics.calculators import trends as trends_calc
from app.analytics.calculators.customers import RetentionRate, TopCustomer
from app.analytics.calculators.invoices import InvoiceCounts
from app.analytics.calculators.payments import AveragePaymentTime
from app.analytics.calculators.products import ProductRevenue
from app.analytics.calculators.revenue import RevenueBreakdown
from app.analytics.calculators.trends import SeriesGranularity, SeriesPoint
from app.analytics.comparison import PeriodComparison
from app.analytics.forecast import Forecast, ForecastMethod, forecast_next_period
from app.analytics.time_windows import TimeWindow, TimeWindowKind, resolve_time_window, trailing_month_starts
from app.models import Customer, Invoice
from app.payment_status import PaymentStatus
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

RECENT_INVOICES_LIMIT = 5
MONTHLY_SUMMARY_MONTHS = 6
TOP_CUSTOMERS_LIMIT = 5
TOP_PRODUCTS_LIMIT = 5


@dataclass(frozen=True)
class AnalyticsService:
    db: Session
    organization_id: str

    # --- KPI engine: one method per reusable metric --------------------

    def revenue_by_currency(self, window: TimeWindow | None = None) -> dict:
        return revenue_calc.get_revenue_by_currency(self.db, self.organization_id, window=window)

    def revenue_breakdown(self, window: TimeWindow | None = None) -> list[RevenueBreakdown]:
        return revenue_calc.get_revenue_breakdown(self.db, self.organization_id, window=window)

    def revenue_growth(self, *, current: TimeWindow, previous: TimeWindow) -> dict:
        return revenue_calc.get_revenue_growth(
            self.db, self.organization_id, current=current, previous=previous
        )

    def pending_revenue_by_currency(self) -> dict:
        return invoices_calc.get_pending_by_currency(self.db, self.organization_id)

    def invoice_counts(self, window: TimeWindow | None = None) -> InvoiceCounts:
        return invoices_calc.get_invoice_counts(self.db, self.organization_id, window=window)

    def average_invoice_value(self, window: TimeWindow | None = None) -> dict:
        return invoices_calc.get_average_invoice_value(self.db, self.organization_id, window=window)

    def customer_growth(self, window: TimeWindow) -> int:
        return customers_calc.get_customer_growth(self.db, self.organization_id, window=window)

    def customer_retention(self) -> RetentionRate:
        return customers_calc.get_customer_retention(self.db, self.organization_id)

    def top_customers(
        self, *, limit: int = TOP_CUSTOMERS_LIMIT, window: TimeWindow | None = None
    ) -> list[TopCustomer]:
        return customers_calc.get_top_customers(
            self.db, self.organization_id, limit=limit, window=window
        )

    def top_products(self, *, limit: int = TOP_PRODUCTS_LIMIT) -> list[ProductRevenue]:
        return products_calc.get_top_products(self.db, self.organization_id, limit=limit)

    def quote_acceptance_rate(self) -> float | None:
        return quotes_calc.get_quote_acceptance_rate(self.db, self.organization_id)

    def average_payment_time(self) -> AveragePaymentTime:
        return payments_calc.get_average_payment_time(self.db, self.organization_id)

    # --- Phase 16C: trend engine -----------------------------------------
    # Period-over-period comparisons and multi-period evolution series,
    # each a one-line delegation to app.analytics.calculators.trends --
    # same discipline as the KPI methods above.

    def revenue_trend(
        self, *, current: TimeWindow, previous: TimeWindow
    ) -> dict[str, PeriodComparison]:
        return trends_calc.get_revenue_trend(
            self.db, self.organization_id, current=current, previous=previous
        )

    def invoice_count_trend(
        self, *, current: TimeWindow, previous: TimeWindow
    ) -> PeriodComparison:
        return trends_calc.get_invoice_count_trend(
            self.db, self.organization_id, current=current, previous=previous
        )

    def customer_growth_trend(
        self, *, current: TimeWindow, previous: TimeWindow
    ) -> PeriodComparison:
        return trends_calc.get_customer_growth_trend(
            self.db, self.organization_id, current=current, previous=previous
        )

    def quote_count_trend(
        self, *, current: TimeWindow, previous: TimeWindow
    ) -> PeriodComparison:
        return trends_calc.get_quote_count_trend(
            self.db, self.organization_id, current=current, previous=previous
        )

    def revenue_series(
        self, period_starts: list[datetime], granularity: SeriesGranularity
    ) -> list[SeriesPoint]:
        return trends_calc.get_revenue_series(
            self.db, self.organization_id, period_starts, granularity
        )

    def invoice_count_series(
        self, period_starts: list[datetime], granularity: SeriesGranularity
    ) -> list[SeriesPoint]:
        return trends_calc.get_invoice_count_series(
            self.db, self.organization_id, period_starts, granularity
        )

    def customer_count_series(
        self, period_starts: list[datetime], granularity: SeriesGranularity
    ) -> list[SeriesPoint]:
        return trends_calc.get_customer_count_series(
            self.db, self.organization_id, period_starts, granularity
        )

    def quote_conversion_series(
        self, period_starts: list[datetime], granularity: SeriesGranularity
    ) -> list[SeriesPoint]:
        return trends_calc.get_quote_conversion_series(
            self.db, self.organization_id, period_starts, granularity
        )

    def revenue_forecast(
        self,
        period_starts: list[datetime],
        granularity: SeriesGranularity,
        *,
        method: ForecastMethod = ForecastMethod.simple_moving_average,
    ) -> dict[str, Forecast]:
        """One Forecast per currency, each built from that currency's own
        revenue_series history -- never a cross-currency figure. Series
        points already arrive in ascending period order (see
        get_revenue_series), so filtering by currency preserves
        chronological order without a second sort."""
        series = self.revenue_series(period_starts, granularity)
        currencies = sorted({point.currency_code for point in series if point.currency_code})
        return {
            code: forecast_next_period(
                [point.value for point in series if point.currency_code == code], method=method
            )
            for code in currencies
        }

    def invoice_count_forecast(
        self,
        period_starts: list[datetime],
        granularity: SeriesGranularity,
        *,
        method: ForecastMethod = ForecastMethod.simple_moving_average,
    ) -> Forecast:
        series = self.invoice_count_series(period_starts, granularity)
        return forecast_next_period([point.value for point in series], method=method)

    # --- Dashboard payload assembly -------------------------------------
    # Relocated verbatim (same computation, same output shape) from
    # app.routers.dashboard.get_dashboard_summary /
    # get_dashboard_analytics_data. Kept as two methods, not decomposed
    # further, because DashboardResponse/DashboardAnalyticsResponse are
    # themselves view-shaped aggregates (built for exactly one screen),
    # not reusable metrics -- the reusable pieces they're built FROM are
    # the KPI methods above, each independently callable and testable on
    # its own.

    def dashboard_summary(self) -> DashboardResponse:
        now = datetime.now(timezone.utc)
        this_month = resolve_time_window(TimeWindowKind.current_month, now=now)
        last_month = resolve_time_window(TimeWindowKind.previous_month, now=now)

        total_invoices_counts = self.invoice_counts()
        total_customers = (
            self.db.scalar(
                select(func.count())
                .select_from(Customer)
                .where(Customer.organization_id == self.organization_id)
            )
            or 0
        )

        total_by_currency = self.revenue_by_currency()
        this_month_by_currency = self.revenue_by_currency(window=this_month)
        last_month_by_currency = self.revenue_by_currency(window=last_month)
        growth_by_currency = self.revenue_growth(current=this_month, previous=last_month)

        currency_codes = (
            set(total_by_currency) | set(this_month_by_currency) | set(last_month_by_currency)
        )
        revenue_by_currency: list[CurrencyRevenueSummary] = []
        for code in sorted(currency_codes):
            revenue_by_currency.append(
                CurrencyRevenueSummary(
                    currency_code=code,
                    total_revenue=total_by_currency.get(code, 0),
                    revenue_this_month=this_month_by_currency.get(code, 0),
                    revenue_last_month=last_month_by_currency.get(code, 0),
                    revenue_growth_percent=growth_by_currency.get(code),
                )
            )

        recent_invoices = self.db.scalars(
            select(Invoice)
            .options(selectinload(Invoice.customer))
            .where(Invoice.organization_id == self.organization_id)
            .order_by(Invoice.created_at.desc())
            .limit(RECENT_INVOICES_LIMIT)
        ).all()

        return DashboardResponse(
            total_invoices=total_invoices_counts.total,
            total_customers=total_customers,
            pending_invoices=total_invoices_counts.pending,
            paid_invoices=total_invoices_counts.paid,
            overdue_invoices=total_invoices_counts.overdue,
            revenue_by_currency=revenue_by_currency,
            recent_invoices=list(recent_invoices),
        )

    def dashboard_analytics(self) -> DashboardAnalyticsResponse:
        month_starts = trailing_month_starts(MONTHLY_SUMMARY_MONTHS)

        monthly_summary = [
            MonthlySummaryPoint(month=month, invoice_count=count)
            for month, count in invoices_calc.get_monthly_invoice_counts(
                self.db, self.organization_id, month_starts
            )
        ]
        monthly_revenue_by_currency = [
            MonthlyRevenuePoint(month=month, currency_code=currency_code, revenue=revenue)
            for month, currency_code, revenue in revenue_calc.get_monthly_revenue_series(
                self.db, self.organization_id, month_starts
            )
        ]

        status_counts = self.invoice_counts()
        status_counts_by_value = {
            PaymentStatus.pending.value: status_counts.pending,
            PaymentStatus.paid.value: status_counts.paid,
            PaymentStatus.overdue.value: status_counts.overdue,
        }
        invoice_count_by_status = [
            PaymentStatusCountPoint(status=status, count=status_counts_by_value.get(status.value, 0))
            for status in PaymentStatus
        ]

        top_customers = [
            TopCustomerRevenue(
                customer_id=row.customer_id,
                customer_name=row.customer_name,
                currency_code=row.currency_code,
                revenue=row.revenue,
            )
            for row in self.top_customers()
        ]
        top_products_and_services = [
            TopProductRevenue(
                product_id=row.product_id,
                product_name=row.product_name,
                product_type=row.product_type,
                currency_code=row.currency_code,
                revenue=row.revenue,
                invoice_count=row.invoice_count,
            )
            for row in self.top_products()
        ]

        pipeline_data = quotes_calc.get_quote_pipeline(self.db, self.organization_id)
        quote_pipeline = QuotePipelineSummary(
            counts_by_status=[
                QuoteStatusCountPoint(
                    status=status, count=pipeline_data.counts_by_status.get(status.value, 0)
                )
                for status in QuoteStatus
            ],
            acceptance_rate_percent=pipeline_data.acceptance_rate_percent,
            by_currency=[
                QuoteCurrencyPipelineSummary(
                    currency_code=row.currency_code,
                    revenue_in_quotes=row.revenue_in_quotes,
                    projected_revenue=row.projected_revenue,
                    accepted_this_month=row.accepted_this_month,
                    rejected_this_month=row.rejected_this_month,
                    converted_this_month=row.converted_this_month,
                )
                for row in pipeline_data.by_currency
            ],
        )
        quote_monthly_conversions = [
            QuoteMonthlyConversionPoint(month=point.month, converted_count=point.converted_count)
            for point in quotes_calc.get_quote_monthly_conversion_series(
                self.db, self.organization_id, month_starts
            )
        ]

        team_summary_data = get_team_summary(self.db, self.organization_id)
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
