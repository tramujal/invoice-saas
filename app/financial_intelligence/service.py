"""FinancialIntelligenceService -- the one orchestration facade every
Financial Intelligence router endpoint calls (Phase 24.1). Every function
here re-checks require_advanced_financial_analytics before delegating to
metrics.py/cashflow.py -- callers (routers, and in future phases,
forecasting.py/recommendations.py) never have to remember the capability
check themselves, and the deterministic calculation logic in metrics.py/
cashflow.py stays entirely unaware of plan gating.

No business calculation lives here or in the router -- every function
below is a one-line capability check plus delegation, matching
app.routers.analytics's own "router stays thin, calculators own the
math" discipline.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.billing.enforcement import require_advanced_financial_analytics, require_ai_financial_recommendations
from app.financial_intelligence import cache, forecasting, metrics, recommendations
from app.financial_intelligence.schemas_ai import FinancialAnalysisPayload, InsightReportResponse
from app.financial_report_status import FinancialReportStatus
from app.models import FinancialInsightReport
from app.financial_intelligence.forecasting import (
    AnomaliesResponse,
    CollectionsForecastResponse,
    ForecastAccuracyResponse,
    ForecastMethodsResponse,
    ForecastSummaryResponse,
    MonthlyProjectionResponse,
    RevenueForecastResponse,
    ScenarioAssumptions,
    ScenarioName,
    ScenarioResponse,
)
from app.financial_intelligence.schemas import (
    CashflowCalendarResponse,
    CustomersSectionResponse,
    ExecutiveOverviewResponse,
    ProductsSectionResponse,
    QuotesSectionResponse,
    ReceivablesAgingResponse,
    RevenueTrendsResponse,
)


def get_executive_overview(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ExecutiveOverviewResponse:
    require_advanced_financial_analytics(db, organization_id)
    return metrics.build_executive_overview(db, organization_id, now=now)


def get_revenue_trends(
    db: Session, organization_id: str, *, now: datetime | None = None, months: int | None = None
) -> RevenueTrendsResponse:
    require_advanced_financial_analytics(db, organization_id)
    if months is None:
        return metrics.build_revenue_trends_section(db, organization_id, now=now)
    return metrics.build_revenue_trends_section(db, organization_id, now=now, months=months)


def get_receivables_aging(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ReceivablesAgingResponse:
    require_advanced_financial_analytics(db, organization_id)
    return metrics.build_receivables_section(db, organization_id, now=now)


def get_customers_section(
    db: Session, organization_id: str, *, now: datetime | None = None, limit: int | None = None
) -> CustomersSectionResponse:
    require_advanced_financial_analytics(db, organization_id)
    if limit is None:
        return metrics.build_customers_section(db, organization_id, now=now)
    return metrics.build_customers_section(db, organization_id, now=now, limit=limit)


def get_products_section(
    db: Session, organization_id: str, *, now: datetime | None = None, limit: int | None = None
) -> ProductsSectionResponse:
    require_advanced_financial_analytics(db, organization_id)
    if limit is None:
        return metrics.build_products_section(db, organization_id, now=now)
    return metrics.build_products_section(db, organization_id, now=now, limit=limit)


def get_quotes_section(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> QuotesSectionResponse:
    require_advanced_financial_analytics(db, organization_id)
    return metrics.build_quotes_section(db, organization_id, now=now)


def get_cashflow_calendar(
    db: Session,
    organization_id: str,
    *,
    now: datetime | None = None,
    horizon_days: int | None = None,
    granularity: str | None = None,
) -> CashflowCalendarResponse:
    require_advanced_financial_analytics(db, organization_id)
    kwargs = {}
    if horizon_days is not None:
        kwargs["horizon_days"] = horizon_days
    if granularity is not None:
        kwargs["granularity"] = granularity
    return metrics.build_cashflow_calendar_section(db, organization_id, now=now, **kwargs)


# --- Phase 24.2 -- deterministic revenue forecasting ------------------------
#
# No require_* capability check here, deliberately -- revenue_forecasting_
# enabled is a SOFT gate (see app.billing.enforcement's own module
# docstring), and every function in app.financial_intelligence.forecasting
# already checks it and returns a structurally-valid plan_restricted=True
# response itself. Wrapping that in a require_* raise here would turn a
# soft degrade back into a hard 403, exactly the behavior this capability
# is documented NOT to have.


def get_revenue_forecast(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> RevenueForecastResponse:
    return forecasting.build_revenue_forecast_section(db, organization_id, now=now)


def get_collections_forecast(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> CollectionsForecastResponse:
    return forecasting.build_collections_forecast_section(db, organization_id, now=now)


def get_monthly_projection(
    db: Session, organization_id: str, *, now: datetime | None = None, months: int | None = None
) -> MonthlyProjectionResponse:
    if months is None:
        return forecasting.build_monthly_projection_section(db, organization_id, now=now)
    return forecasting.build_monthly_projection_section(db, organization_id, now=now, months=months)


def get_forecast_summary(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ForecastSummaryResponse:
    return forecasting.build_forecast_summary_section(db, organization_id, now=now)


def get_forecast_accuracy(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ForecastAccuracyResponse:
    return forecasting.build_forecast_accuracy_section(db, organization_id, now=now)


def get_forecast_methods(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ForecastMethodsResponse:
    return forecasting.build_forecast_methods_section(db, organization_id, now=now)


def get_anomalies(db: Session, organization_id: str, *, now: datetime | None = None) -> AnomaliesResponse:
    return forecasting.build_anomalies_section(db, organization_id, now=now)


def evaluate_scenario(
    db: Session,
    organization_id: str,
    *,
    scenario: ScenarioName = "base",
    assumptions: ScenarioAssumptions | None = None,
    now: datetime | None = None,
) -> ScenarioResponse:
    return forecasting.evaluate_scenario(
        db, organization_id, scenario=scenario, assumptions=assumptions, now=now
    )


# --- Phase 24.3 -- the AI Financial Advisor ---------------------------------
#
# Unlike revenue forecasting, ai_financial_recommendations_enabled is a
# HARD gate (require_ai_financial_recommendations raises
# CapabilityDeniedError, caught by the router's existing _run() helper) --
# per this phase's own "Free: unavailable" requirement, there is no
# meaningful degraded version of an AI-generated report to fall back to.


def _to_insight_report_response(
    report: FinancialInsightReport, *, reused: bool = False
) -> InsightReportResponse:
    analysis = None
    if report.status == FinancialReportStatus.completed.value and report.structured_payload:
        analysis = FinancialAnalysisPayload.model_validate_json(report.structured_payload)
    return InsightReportResponse(
        id=report.id,
        status=report.status,
        period_start=report.period_start,
        period_end=report.period_end,
        ai_provider=report.ai_provider,
        ai_model=report.ai_model,
        generated_at=report.generated_at,
        expires_at=report.expires_at,
        error_code=report.error_code,
        error_message=report.error_message,
        created_by_user_id=report.created_by_user_id,
        created_at=report.created_at,
        analysis=analysis,
        reused=reused,
    )


def get_latest_insight_report(db: Session, organization_id: str) -> InsightReportResponse | None:
    require_ai_financial_recommendations(db, organization_id)
    report = cache.get_latest_report(db, organization_id)
    if report is None:
        return None
    return _to_insight_report_response(report)


def request_insight_report(
    db: Session, organization_id: str, *, requested_by_user_id: str, force: bool = False
) -> InsightReportResponse:
    require_ai_financial_recommendations(db, organization_id)
    report, reused = recommendations.request_insight_report(
        db, organization_id, requested_by_user_id=requested_by_user_id, force=force
    )
    return _to_insight_report_response(report, reused=reused)
