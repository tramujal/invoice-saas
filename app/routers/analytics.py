"""GET /organizations/{organization_id}/analytics/kpis -- a single,
window-parameterized snapshot of the core KPI-engine metrics
(app.analytics.calculators), assembled entirely by AnalyticsService.

Deliberately the only route in this router for now: Phase 16A's job is
the analytics DOMAIN (AnalyticsService, calculators, time windows), not a
new dashboard UI -- see that phase's own completion report for the full
rationale. Every metric this endpoint returns is already independently
callable through AnalyticsService; adding a second, more specific route
later (e.g. a dedicated top-customers or revenue-trend endpoint) is a
router-only change, never a recomputation -- exactly the point of
building the calculator layer first.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics.calculators.trends import SeriesGranularity
from app.analytics.forecast import ForecastMethod
from app.analytics.service import AnalyticsService
from app.analytics.time_windows import (
    COMPARISON_KINDS,
    TimeWindowKind,
    resolve_period_comparison_windows,
    resolve_time_window,
    trailing_month_starts,
    trailing_quarter_starts,
    trailing_year_starts,
)
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import Organization, User
from app.permissions import Permission
from app.schemas import (
    AveragePaymentTimeResponse,
    CustomerRetentionResponse,
    ForecastResponse,
    InvoiceCountsResponse,
    KpiSnapshotResponse,
    PeriodComparisonResponse,
    RevenueBreakdownResponse,
    SeriesPointResponse,
    TimeWindowResponse,
    TrendSnapshotResponse,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/analytics", tags=["analytics"]
)


@router.get("/kpis", response_model=KpiSnapshotResponse)
def get_kpi_snapshot(
    organization_id: str,
    window: TimeWindowKind = Query(default=TimeWindowKind.current_month),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KpiSnapshotResponse:
    # Reuses the exact same permission this data already required when it
    # only lived behind the dashboard endpoints -- this is the same
    # figures, just newly queryable on their own by window.
    require_permission(current_user, organization_id, Permission.dashboard_view, db)

    if window == TimeWindowKind.custom:
        # A custom range needs explicit start/end query params this route
        # doesn't accept yet -- an honest 400 rather than silently
        # resolving to a meaningless default range.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "custom_window_not_supported",
                "message": "window=custom is not supported by this endpoint yet.",
            },
        )

    organization = db.get(Organization, organization_id)
    resolved = resolve_time_window(window, organization=organization)
    service = AnalyticsService(db, organization_id)

    invoice_counts = service.invoice_counts(resolved)
    retention = service.customer_retention()
    payment_time = service.average_payment_time()

    return KpiSnapshotResponse(
        window=TimeWindowResponse(kind=resolved.kind.value, start=resolved.start, end=resolved.end),
        invoice_counts=InvoiceCountsResponse(
            total=invoice_counts.total,
            pending=invoice_counts.pending,
            paid=invoice_counts.paid,
            overdue=invoice_counts.overdue,
        ),
        revenue_by_currency=service.revenue_by_currency(resolved),
        revenue_breakdown=[
            RevenueBreakdownResponse(
                currency_code=b.currency_code,
                total=b.total,
                paid=b.paid,
                outstanding=b.outstanding,
                overdue=b.overdue,
            )
            for b in service.revenue_breakdown(resolved)
        ],
        average_invoice_value=service.average_invoice_value(resolved),
        customer_growth=service.customer_growth(resolved),
        customer_retention=CustomerRetentionResponse(
            total_invoiced_customers=retention.total_invoiced_customers,
            repeat_customers=retention.repeat_customers,
            retention_rate_percent=retention.retention_rate_percent,
        ),
        quote_acceptance_rate_percent=service.quote_acceptance_rate(),
        average_payment_time=AveragePaymentTimeResponse(
            available=payment_time.available,
            average_days=payment_time.average_days,
            reason=payment_time.reason,
        ),
    )


# --- Phase 16C: trend analysis & forecasting ---------------------------

# One default trailing-period count per granularity -- enough history for
# a meaningful moving-average/linear-trend forecast without an unbounded
# query range. 6 months mirrors AnalyticsService.dashboard_analytics' own
# MONTHLY_SUMMARY_MONTHS; 4 quarters is a full trailing year; 3 years is
# enough for a linear trend without reaching back through an org's entire
# lifetime by default.
DEFAULT_PERIODS_BY_GRANULARITY: dict[SeriesGranularity, int] = {
    SeriesGranularity.monthly: 6,
    SeriesGranularity.quarterly: 4,
    SeriesGranularity.yearly: 3,
}

_TRAILING_STARTS_FN = {
    SeriesGranularity.monthly: trailing_month_starts,
    SeriesGranularity.quarterly: trailing_quarter_starts,
    SeriesGranularity.yearly: trailing_year_starts,
}


def _comparison_response(comparison) -> PeriodComparisonResponse:
    return PeriodComparisonResponse(
        current=comparison.current,
        previous=comparison.previous,
        absolute_difference=comparison.absolute_difference,
        percentage_difference=comparison.percentage_difference,
        direction=comparison.direction.value,
    )


def _series_response(points) -> list[SeriesPointResponse]:
    return [
        SeriesPointResponse(period=p.period, value=p.value, currency_code=p.currency_code)
        for p in points
    ]


def _forecast_response(forecast) -> ForecastResponse:
    return ForecastResponse(
        available=forecast.available,
        method=forecast.method.value if forecast.method is not None else None,
        forecast_value=forecast.forecast_value,
        inputs=forecast.inputs,
        window_size=forecast.window_size,
        reason=forecast.reason,
    )


@router.get("/trends", response_model=TrendSnapshotResponse)
def get_trend_snapshot(
    organization_id: str,
    comparison: TimeWindowKind = Query(default=TimeWindowKind.current_month),
    granularity: SeriesGranularity = Query(default=SeriesGranularity.monthly),
    periods: int | None = Query(default=None, ge=2, le=36),
    method: ForecastMethod = Query(default=ForecastMethod.simple_moving_average),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TrendSnapshotResponse:
    """Period-over-period comparisons, generic evolution series, and
    short-term forecasts -- entirely additive alongside GET .../kpis
    (Phase 16B); that route's shape and behavior are untouched by this
    one. Same permission gate: this is the same underlying data, just a
    different cut of it.
    """
    require_permission(current_user, organization_id, Permission.dashboard_view, db)

    if comparison not in COMPARISON_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unsupported_comparison_kind",
                "message": (
                    f"comparison={comparison.value} is not supported; must be one of "
                    f"{[k.value for k in COMPARISON_KINDS]}."
                ),
            },
        )

    organization = db.get(Organization, organization_id)
    current_window, previous_window = resolve_period_comparison_windows(
        comparison, organization=organization
    )

    period_count = periods or DEFAULT_PERIODS_BY_GRANULARITY[granularity]
    period_starts = _TRAILING_STARTS_FN[granularity](period_count)

    service = AnalyticsService(db, organization_id)

    return TrendSnapshotResponse(
        comparison_kind=comparison.value,
        granularity=granularity.value,
        revenue_trend={
            code: _comparison_response(c)
            for code, c in service.revenue_trend(current=current_window, previous=previous_window).items()
        },
        invoice_count_trend=_comparison_response(
            service.invoice_count_trend(current=current_window, previous=previous_window)
        ),
        customer_growth_trend=_comparison_response(
            service.customer_growth_trend(current=current_window, previous=previous_window)
        ),
        quote_count_trend=_comparison_response(
            service.quote_count_trend(current=current_window, previous=previous_window)
        ),
        revenue_series=_series_response(service.revenue_series(period_starts, granularity)),
        invoice_count_series=_series_response(
            service.invoice_count_series(period_starts, granularity)
        ),
        customer_count_series=_series_response(
            service.customer_count_series(period_starts, granularity)
        ),
        quote_conversion_series=_series_response(
            service.quote_conversion_series(period_starts, granularity)
        ),
        revenue_forecast={
            code: _forecast_response(f)
            for code, f in service.revenue_forecast(period_starts, granularity, method=method).items()
        },
        invoice_count_forecast=_forecast_response(
            service.invoice_count_forecast(period_starts, granularity, method=method)
        ),
    )
