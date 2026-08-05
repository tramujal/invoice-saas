"""Phase 24.2 -- deterministic revenue forecasting, expected collections,
monthly projections, scenario analysis, and anomaly detection.

Every number in this module is a reproducible transformation of real
Invoice/Quote rows through app.financial_intelligence.models (the
candidate forecast models) and app.financial_intelligence.backtesting
(rolling-origin model selection) -- no AI, no external statistics
package. Scenarios (see evaluate_scenario) never touch stored business
data; they only re-run this same deterministic math with user-adjustable
multipliers on top of the Base forecast.

Soft plan gating: unlike require_advanced_financial_analytics (a hard
403), revenue_forecasting_enabled degrades SOFTLY -- every function below
checks can_use_revenue_forecasting itself and returns a structurally
valid, empty (`plan_restricted=True`) response rather than raising. This
is the exact behavior app.billing.enforcement's own module docstring
already promises for this capability ("returning a structurally-valid
forecast response with plan_restricted=True instead of rejecting the
request") -- the same soft-degrade the pre-existing /analytics/trends
forecast already uses. Because the check lives here (not in service.py),
service.py's forecasting wrappers are plain delegation with no capability
check of their own.

Every response's free-text is deliberately narrow: `AnomalyFlag.evidence`
is a factual, data-driven readout (mirrors the already-established
AtRiskCustomer.evidence precedent from Phase 24.1's schemas.py -- shown
directly, not translated, since it states facts rather than narrative
copy). Everything else that would otherwise be English prose (why a
currency is insufficient_data, what a model even means) is instead
exposed as structured fields (`status`, `sample_size`,
`minimum_observations_required`, `method`) for the frontend to build its
own translated copy from -- the same "never render backend free text
directly" discipline enforced throughout Phase 24.1's UI.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics.primitives import growth_percent, quantize_money
from app.analytics.service import AnalyticsService
from app.analytics.time_windows import TimeWindowKind, resolve_time_window, trailing_month_starts
from app.billing.capabilities import can_use_revenue_forecasting, get_organization_capabilities
from app.financial_intelligence import cashflow, models, queries
from app.financial_intelligence.backtesting import ModelEvaluation, select_best_model
from app.financial_intelligence.confidence import ConfidenceLevel, classify_confidence, confidence_interval
from app.financial_intelligence.models import ForecastModelName
from app.financial_intelligence.queries import OpenInvoiceRow
from app.models import Organization
from app.org_time import get_organization_today

# 3 years -- generous enough for two full seasonal cycles (seasonal_naive
# needs one full season just to compute a value, two to ever backtest
# it), yet still a bounded window, matching every other bounded query in
# this package (OPEN_INVOICE_DETAIL_LIMIT, etc).
FORECAST_HISTORY_MONTHS = 36

# Days -> whole months for the monthly forecasting model -- documented,
# approximate mapping (30d = 1 month, ... 365d = 12 months), never a
# fractional month.
HORIZON_MONTHS: dict[int, int] = {30: 1, 90: 3, 180: 6, 365: 12}
REVENUE_HORIZON_DAYS = (30, 90, 180, 365)
COLLECTIONS_HORIZON_DAYS = (30, 90, 180)
# A 365-day-ahead revenue forecast is only shown when there's enough
# history for it to mean something beyond a single linear extrapolation
# -- at least one full year plus one more month, mirroring
# app.financial_intelligence.models.MIN_HISTORY's own seasonal floor.
MIN_HISTORY_FOR_365D_HORIZON = 13

MONTHLY_PROJECTION_DEFAULT_MONTHS = 6
MONTHLY_PROJECTION_MAX_MONTHS = 12

MONEY_QUANTIZE = Decimal("0.01")
PERCENT_QUANTIZE = Decimal("0.01")


# --- Shared building blocks -------------------------------------------------


@dataclass(frozen=True)
class CurrencyHistory:
    """One currency's monthly invoiced/collected series, chronological,
    TRIMMED to start at that currency's own first active month -- leading
    months before an organization ever invoiced in this currency are not
    real "zero" observations, they're the absence of the currency
    existing yet, and would otherwise corrupt eligibility/backtesting
    (e.g. seasonal_naive "seeing" 20 fake leading zero months)."""

    invoiced: list[Decimal]
    collected: list[Decimal]


def _currency_histories(
    db: Session, organization_id: str, *, now: datetime
) -> dict[str, CurrencyHistory]:
    month_starts = trailing_month_starts(FORECAST_HISTORY_MONTHS, now=now)
    rows = queries.get_monthly_revenue_series(db, organization_id, month_starts)
    month_keys = [s.strftime("%Y-%m") for s in month_starts]

    invoiced_by_currency: dict[str, dict[str, Decimal]] = {}
    collected_by_currency: dict[str, dict[str, Decimal]] = {}
    for row in rows:
        invoiced_by_currency.setdefault(row.currency_code, {})[row.month] = row.invoiced
        collected_by_currency.setdefault(row.currency_code, {})[row.month] = row.collected

    histories: dict[str, CurrencyHistory] = {}
    for code, series_by_month in invoiced_by_currency.items():
        invoiced_series = [series_by_month.get(m, Decimal("0")) for m in month_keys]
        first_active = next((i for i, v in enumerate(invoiced_series) if v > 0), None)
        if first_active is None:
            continue
        collected_series_by_month = collected_by_currency.get(code, {})
        collected_series = [collected_series_by_month.get(m, Decimal("0")) for m in month_keys]
        histories[code] = CurrencyHistory(
            invoiced=invoiced_series[first_active:], collected=collected_series[first_active:]
        )
    return histories


def _future_month_labels(now: datetime, months: int) -> list[str]:
    """The next `months` calendar months STRICTLY after the current one
    (the current month's actual-so-far figures already live in the
    Executive overview; projecting it again here would be redundant)."""
    d = date(now.year, now.month, 1)
    labels = []
    for _ in range(months):
        next_month = d.month % 12 + 1
        next_year = d.year + (1 if d.month == 12 else 0)
        d = date(next_year, next_month, 1)
        labels.append(d.strftime("%Y-%m"))
    return labels


def _expected_collection_date(
    invoice: OpenInvoiceRow, *, today_local: date, delay: "cashflow.DelayStats"
) -> date:
    """Identical logic to cashflow._expected_collection_date, parameterized
    by an ALREADY-RESOLVED DelayStats rather than always computing the
    org-wide one itself -- lets callers pass a customer-specific DelayStats
    where one is available (see _known_collections_by_horizon below),
    exactly the refinement cashflow.py's own docstring anticipates this
    phase adding. Deliberately duplicated rather than importing a shared
    private helper from cashflow.py, so Phase 24.1's own
    /cashflow-calendar endpoint is never at risk of an accidental
    behavior change from this phase."""
    if invoice.due_date is None:
        return today_local
    if invoice.due_date >= today_local:
        return invoice.due_date
    if delay.available and delay.average_days is not None:
        return max(invoice.due_date + timedelta(days=int(delay.average_days)), today_local)
    return today_local


def _known_collections_by_horizon(
    db: Session,
    organization_id: str,
    *,
    today_local: date,
    horizon_days_list: tuple[int, ...],
    org_delay: "cashflow.DelayStats",
) -> dict[int, dict[str, Decimal]]:
    """The "known" component of expected collections for every requested
    horizon at once (one pass over currently-open invoices) -- customer-
    aware: each invoice uses ITS OWN customer's historical payment-delay
    average when that customer has enough real observations
    (cashflow.MIN_PAYMENT_DELAY_OBSERVATIONS), falling back to the
    organization-wide average otherwise, per this phase's own "if
    customer history is insufficient, fall back to organization averages"
    requirement. Bounded cost: one compute_payment_delay_stats query per
    DISTINCT customer with an open invoice (cached, never repeated),
    capped by the same OPEN_INVOICE_DETAIL_LIMIT every other detail query
    in this package already bounds itself by."""
    open_invoices = queries.get_open_invoices(db, organization_id)
    delay_cache: dict[str, "cashflow.DelayStats"] = {}
    max_horizon = max(horizon_days_list)
    result: dict[int, dict[str, Decimal]] = {h: {} for h in horizon_days_list}

    for inv in open_invoices:
        effective_delay = org_delay
        if inv.customer_id is not None:
            if inv.customer_id not in delay_cache:
                delay_cache[inv.customer_id] = cashflow.compute_payment_delay_stats(
                    db, organization_id, customer_id=inv.customer_id
                )
            customer_delay = delay_cache[inv.customer_id]
            if customer_delay.available:
                effective_delay = customer_delay

        expected = _expected_collection_date(inv, today_local=today_local, delay=effective_delay)
        if expected < today_local or expected >= today_local + timedelta(days=max_horizon):
            continue
        for horizon_days in horizon_days_list:
            if expected < today_local + timedelta(days=horizon_days):
                bucket = result[horizon_days]
                bucket[inv.currency_code] = bucket.get(inv.currency_code, Decimal("0")) + inv.total
    return result


def _min_observations_for_selection(method: ForecastModelName | None = None) -> int:
    """The TRUE minimum months of history needed before a model can ever
    be genuinely selected -- distinct from models.MIN_HISTORY, which only
    gates whether the model function can compute *a* value at all.
    backtesting._evaluate_one_model starts its rolling-origin loop at
    `MIN_HISTORY[method]`, so a real backtest fold (and therefore
    eligibility for select_best_model) only exists once history is
    STRICTLY GREATER than that floor -- i.e. MIN_HISTORY[method] + 1.
    Reporting the bare MIN_HISTORY value to a user would be dishonest: an
    organization with exactly that many months would still see
    insufficient_data, having been told it had "enough."""
    if method is not None:
        return models.MIN_HISTORY[method.value] + 1
    return min(models.MIN_HISTORY.values()) + 1


def _shift_delay(delay: "cashflow.DelayStats", delta_days: int) -> "cashflow.DelayStats":
    """A scenario's collection_delay_days assumption applied to an
    already-computed DelayStats -- never re-queries history, purely
    arithmetic, and leaves an unavailable DelayStats unavailable (there is
    no real average to shift)."""
    if not delay.available or delay.average_days is None:
        return delay
    return cashflow.DelayStats(
        available=True,
        sample_size=delay.sample_size,
        average_days=delay.average_days + delta_days,
        median_days=delay.median_days,
    )


# --- Schemas -----------------------------------------------------------


class HorizonForecast(BaseModel):
    horizon_days: int
    forecast_value: Decimal
    lower_bound: Decimal
    upper_bound: Decimal


CurrencyForecastStatus = Literal["ok", "insufficient_data"]


class RevenueForecastCurrencyResult(BaseModel):
    currency_code: str
    status: CurrencyForecastStatus
    model: ForecastModelName | None
    sample_size: int
    confidence: ConfidenceLevel
    minimum_observations_required: int
    horizons: list[HorizonForecast]


class RevenueForecastResponse(BaseModel):
    generated_at: datetime
    plan_restricted: bool
    results: list[RevenueForecastCurrencyResult]


class CollectionsHorizonResult(BaseModel):
    horizon_days: int
    known_amount: Decimal
    projected_amount: Decimal
    total_expected: Decimal
    lower_bound: Decimal
    upper_bound: Decimal


class CollectionsForecastCurrencyResult(BaseModel):
    currency_code: str
    sample_size: int
    confidence: ConfidenceLevel
    horizons: list[CollectionsHorizonResult]


class CollectionsForecastResponse(BaseModel):
    generated_at: datetime
    plan_restricted: bool
    results: list[CollectionsForecastCurrencyResult]


class MonthlyProjectionPoint(BaseModel):
    month: str
    currency_code: str
    expected_value: Decimal
    lower_bound: Decimal
    upper_bound: Decimal
    confidence: ConfidenceLevel
    sample_size: int


class MonthlyProjectionResponse(BaseModel):
    generated_at: datetime
    plan_restricted: bool
    months: int
    points: list[MonthlyProjectionPoint]


class ModelAccuracyEntry(BaseModel):
    method: ForecastModelName
    eligible: bool
    fold_count: int
    mae: Decimal | None
    wape: Decimal | None
    mape: Decimal | None
    directional_accuracy_percent: Decimal | None
    selected: bool


class ForecastAccuracyCurrencyResult(BaseModel):
    currency_code: str
    sample_size: int
    selected_model: ForecastModelName | None
    evaluations: list[ModelAccuracyEntry]


class ForecastAccuracyResponse(BaseModel):
    generated_at: datetime
    plan_restricted: bool
    results: list[ForecastAccuracyCurrencyResult]


class ForecastMethodDescription(BaseModel):
    method: ForecastModelName
    minimum_observations_required: int


class ForecastMethodsResponse(BaseModel):
    generated_at: datetime
    plan_restricted: bool
    methods: list[ForecastMethodDescription]


AnomalyRule = Literal[
    "revenue_drop", "collection_slowdown", "overdue_spike", "large_invoice", "customer_concentration"
]
AnomalySeverity = Literal["low", "medium", "high"]


class AnomalyFlag(BaseModel):
    rule: AnomalyRule
    severity: AnomalySeverity
    currency_code: str | None
    sample_size: int
    # A factual, data-driven readout -- see module docstring on why this
    # (unlike MetricValue.label/note) is safe to render directly.
    evidence: str


class AnomaliesResponse(BaseModel):
    generated_at: datetime
    plan_restricted: bool
    flags: list[AnomalyFlag]


ScenarioName = Literal["base", "optimistic", "conservative"]


class ScenarioAssumptions(BaseModel):
    invoice_growth_percent: Decimal = Decimal("0")
    collection_delay_days: int = 0
    quote_conversion_delta_percent: Decimal = Decimal("0")


SCENARIO_PRESETS: dict[ScenarioName, ScenarioAssumptions] = {
    "base": ScenarioAssumptions(),
    "optimistic": ScenarioAssumptions(
        invoice_growth_percent=Decimal("10"), collection_delay_days=-5, quote_conversion_delta_percent=Decimal("10")
    ),
    "conservative": ScenarioAssumptions(
        invoice_growth_percent=Decimal("-10"), collection_delay_days=5, quote_conversion_delta_percent=Decimal("-10")
    ),
}


class ScenarioCurrencyResult(BaseModel):
    currency_code: str
    revenue_horizons: list[HorizonForecast]
    collections_horizons: list[CollectionsHorizonResult]


class ScenarioResponse(BaseModel):
    generated_at: datetime
    plan_restricted: bool
    scenario: ScenarioName
    assumptions_used: ScenarioAssumptions
    results: list[ScenarioCurrencyResult]


class ForecastSummaryCurrencyResult(BaseModel):
    currency_code: str
    model: ForecastModelName | None
    confidence: ConfidenceLevel
    revenue_90d: HorizonForecast | None
    collections_90d: CollectionsHorizonResult | None
    anomaly_count: int


class ForecastSummaryResponse(BaseModel):
    generated_at: datetime
    plan_restricted: bool
    results: list[ForecastSummaryCurrencyResult]


# --- 1. Expected collections --------------------------------------------


def build_revenue_forecast_section(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> RevenueForecastResponse:
    now = now or datetime.now(timezone.utc)
    caps = get_organization_capabilities(db, organization_id)
    if not can_use_revenue_forecasting(caps):
        return RevenueForecastResponse(generated_at=now, plan_restricted=True, results=[])

    histories = _currency_histories(db, organization_id, now=now)
    results: list[RevenueForecastCurrencyResult] = []
    max_months = max(HORIZON_MONTHS.values())

    for code in sorted(histories):
        history = histories[code].invoiced
        sample_size = len(history)
        method, evaluations = select_best_model(history)

        if method is None:
            results.append(
                RevenueForecastCurrencyResult(
                    currency_code=code,
                    status="insufficient_data",
                    model=None,
                    sample_size=sample_size,
                    confidence=ConfidenceLevel.insufficient_data,
                    minimum_observations_required=_min_observations_for_selection(),
                    horizons=[],
                )
            )
            continue

        selected_eval = next(e for e in evaluations if e.method == method)
        confidence = classify_confidence(sample_size, selected_eval.wape)
        forecast = models.forecast_with(method, history, steps=max_months)

        horizons: list[HorizonForecast] = []
        for horizon_days in REVENUE_HORIZON_DAYS:
            if horizon_days == 365 and sample_size < MIN_HISTORY_FOR_365D_HORIZON:
                continue
            month_count = HORIZON_MONTHS[horizon_days]
            cumulative = quantize_money(sum(forecast.values[:month_count], Decimal("0")))
            lower, upper = confidence_interval(
                cumulative, wape=selected_eval.wape, steps_ahead=month_count
            )
            horizons.append(
                HorizonForecast(
                    horizon_days=horizon_days, forecast_value=cumulative, lower_bound=lower, upper_bound=upper
                )
            )

        results.append(
            RevenueForecastCurrencyResult(
                currency_code=code,
                status="ok",
                model=method,
                sample_size=sample_size,
                confidence=confidence,
                minimum_observations_required=_min_observations_for_selection(method),
                horizons=horizons,
            )
        )

    return RevenueForecastResponse(generated_at=now, plan_restricted=False, results=results)


# --- 2. Expected collections --------------------------------------------


def build_collections_forecast_section(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> CollectionsForecastResponse:
    now = now or datetime.now(timezone.utc)
    caps = get_organization_capabilities(db, organization_id)
    if not can_use_revenue_forecasting(caps):
        return CollectionsForecastResponse(generated_at=now, plan_restricted=True, results=[])

    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    histories = _currency_histories(db, organization_id, now=now)
    org_delay = cashflow.compute_payment_delay_stats(db, organization_id)
    known_by_horizon = _known_collections_by_horizon(
        db, organization_id, today_local=today_local, horizon_days_list=COLLECTIONS_HORIZON_DAYS,
        org_delay=org_delay,
    )

    open_invoice_currencies = {inv.currency_code for inv in queries.get_open_invoices(db, organization_id)}
    currencies = sorted(set(histories) | open_invoice_currencies)

    results: list[CollectionsForecastCurrencyResult] = []
    for code in currencies:
        history = histories.get(code)
        sample_size = len(history.invoiced) if history else 0
        method, evaluations = select_best_model(history.invoiced) if history else (None, [])
        selected_wape = next((e.wape for e in evaluations if e.method == method), None) if method else None
        collection_rate = (
            (sum(history.collected, Decimal("0")) / sum(history.invoiced, Decimal("0")))
            if history and sum(history.invoiced, Decimal("0")) > 0
            else None
        )

        horizons: list[CollectionsHorizonResult] = []
        for horizon_days in COLLECTIONS_HORIZON_DAYS:
            month_count = HORIZON_MONTHS[horizon_days]
            known = known_by_horizon[horizon_days].get(code, Decimal("0"))
            projected = Decimal("0")
            if history is not None and method is not None and collection_rate is not None:
                future_forecast = models.forecast_with(method, history.invoiced, steps=month_count)
                projected = quantize_money(
                    sum(future_forecast.values, Decimal("0")) * collection_rate
                )
            total = quantize_money(known + projected)
            lower, upper = confidence_interval(total, wape=selected_wape, steps_ahead=month_count)
            horizons.append(
                CollectionsHorizonResult(
                    horizon_days=horizon_days,
                    known_amount=quantize_money(known),
                    projected_amount=projected,
                    total_expected=total,
                    lower_bound=lower,
                    upper_bound=upper,
                )
            )

        confidence = classify_confidence(sample_size, selected_wape) if sample_size else ConfidenceLevel.insufficient_data
        results.append(
            CollectionsForecastCurrencyResult(
                currency_code=code, sample_size=sample_size, confidence=confidence, horizons=horizons
            )
        )

    return CollectionsForecastResponse(generated_at=now, plan_restricted=False, results=results)


# --- 3. Monthly projection -----------------------------------------------


def build_monthly_projection_section(
    db: Session,
    organization_id: str,
    *,
    now: datetime | None = None,
    months: int = MONTHLY_PROJECTION_DEFAULT_MONTHS,
) -> MonthlyProjectionResponse:
    now = now or datetime.now(timezone.utc)
    caps = get_organization_capabilities(db, organization_id)
    if not can_use_revenue_forecasting(caps):
        return MonthlyProjectionResponse(generated_at=now, plan_restricted=True, months=months, points=[])

    months = max(1, min(months, MONTHLY_PROJECTION_MAX_MONTHS))
    histories = _currency_histories(db, organization_id, now=now)
    month_labels = _future_month_labels(now, months)

    points: list[MonthlyProjectionPoint] = []
    for code in sorted(histories):
        history = histories[code].invoiced
        sample_size = len(history)
        method, evaluations = select_best_model(history)
        if method is None:
            continue
        selected_eval = next(e for e in evaluations if e.method == method)
        confidence = classify_confidence(sample_size, selected_eval.wape)
        forecast = models.forecast_with(method, history, steps=months)

        for index, label in enumerate(month_labels):
            value = forecast.values[index]
            lower, upper = confidence_interval(value, wape=selected_eval.wape, steps_ahead=index + 1)
            points.append(
                MonthlyProjectionPoint(
                    month=label,
                    currency_code=code,
                    expected_value=value,
                    lower_bound=lower,
                    upper_bound=upper,
                    confidence=confidence,
                    sample_size=sample_size,
                )
            )

    return MonthlyProjectionResponse(generated_at=now, plan_restricted=False, months=months, points=points)


# --- 4. Forecast accuracy / methods (transparency) -----------------------


def build_forecast_accuracy_section(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ForecastAccuracyResponse:
    now = now or datetime.now(timezone.utc)
    caps = get_organization_capabilities(db, organization_id)
    if not can_use_revenue_forecasting(caps):
        return ForecastAccuracyResponse(generated_at=now, plan_restricted=True, results=[])

    histories = _currency_histories(db, organization_id, now=now)
    results: list[ForecastAccuracyCurrencyResult] = []
    for code in sorted(histories):
        history = histories[code].invoiced
        method, evaluations = select_best_model(history)
        entries = [
            ModelAccuracyEntry(
                method=e.method,
                eligible=e.eligible,
                fold_count=e.fold_count,
                mae=e.mae,
                wape=e.wape,
                mape=e.mape,
                directional_accuracy_percent=e.directional_accuracy_percent,
                selected=(e.method == method),
            )
            for e in evaluations
        ]
        results.append(
            ForecastAccuracyCurrencyResult(
                currency_code=code, sample_size=len(history), selected_model=method, evaluations=entries
            )
        )
    return ForecastAccuracyResponse(generated_at=now, plan_restricted=False, results=results)


def build_forecast_methods_section(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ForecastMethodsResponse:
    now = now or datetime.now(timezone.utc)
    caps = get_organization_capabilities(db, organization_id)
    if not can_use_revenue_forecasting(caps):
        return ForecastMethodsResponse(generated_at=now, plan_restricted=True, methods=[])

    methods = [
        ForecastMethodDescription(method=m, minimum_observations_required=_min_observations_for_selection(m))
        for m in ForecastModelName
    ]
    return ForecastMethodsResponse(generated_at=now, plan_restricted=False, methods=methods)


# --- 5. Anomaly detection -------------------------------------------------

REVENUE_DROP_MEDIUM_THRESHOLD = Decimal("-20")
REVENUE_DROP_HIGH_THRESHOLD = Decimal("-40")
COLLECTION_SLOWDOWN_WINDOW_DAYS = 90
COLLECTION_SLOWDOWN_MULTIPLIER = Decimal("1.5")
MIN_RECENT_DELAY_OBSERVATIONS = 5
OVERDUE_SPIKE_BASELINE_DAYS_AGO = 30
OVERDUE_SPIKE_MULTIPLIER = Decimal("1.5")
OVERDUE_SPIKE_MIN_ABSOLUTE = Decimal("100")
LARGE_INVOICE_MULTIPLIER = Decimal("3")
CONCENTRATION_MEDIUM_THRESHOLD = Decimal("50")
CONCENTRATION_HIGH_THRESHOLD = Decimal("75")


def build_anomalies_section(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> AnomaliesResponse:
    now = now or datetime.now(timezone.utc)
    caps = get_organization_capabilities(db, organization_id)
    if not can_use_revenue_forecasting(caps):
        return AnomaliesResponse(generated_at=now, plan_restricted=True, flags=[])

    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    flags: list[AnomalyFlag] = []

    # revenue_drop -- latest vs. previous month, per currency.
    histories = _currency_histories(db, organization_id, now=now)
    for code, hist in histories.items():
        if len(hist.invoiced) < 2:
            continue
        latest, previous = hist.invoiced[-1], hist.invoiced[-2]
        change = growth_percent(latest, previous)
        if change is not None and change <= REVENUE_DROP_MEDIUM_THRESHOLD:
            severity: AnomalySeverity = "high" if change <= REVENUE_DROP_HIGH_THRESHOLD else "medium"
            flags.append(
                AnomalyFlag(
                    rule="revenue_drop",
                    severity=severity,
                    currency_code=code,
                    sample_size=len(hist.invoiced),
                    evidence=(
                        f"Invoiced revenue fell {abs(change)}% month-over-month "
                        f"({previous} -> {latest} {code})."
                    ),
                )
            )

    # collection_slowdown -- recent (90-day) average delay vs. all-time.
    org_delay = cashflow.compute_payment_delay_stats(db, organization_id)
    since = datetime.combine(
        today_local - timedelta(days=COLLECTION_SLOWDOWN_WINDOW_DAYS), datetime.min.time()
    ).replace(tzinfo=timezone.utc)
    recent_observations = queries.get_recent_payment_delay_observations(db, organization_id, since=since)
    if (
        org_delay.available
        and org_delay.average_days is not None
        and org_delay.average_days > 0
        and len(recent_observations) >= MIN_RECENT_DELAY_OBSERVATIONS
    ):
        recent_average = Decimal(sum(recent_observations)) / Decimal(len(recent_observations))
        if recent_average > org_delay.average_days * COLLECTION_SLOWDOWN_MULTIPLIER:
            flags.append(
                AnomalyFlag(
                    rule="collection_slowdown",
                    severity="medium",
                    currency_code=None,
                    sample_size=len(recent_observations),
                    evidence=(
                        f"Recent average payment delay ({recent_average.quantize(PERCENT_QUANTIZE)} days) "
                        f"is more than {COLLECTION_SLOWDOWN_MULTIPLIER}x this organization's historical "
                        f"average ({org_delay.average_days} days)."
                    ),
                )
            )

    # overdue_spike -- current overdue balance vs. 30 days ago, per currency.
    baseline_date = today_local - timedelta(days=OVERDUE_SPIKE_BASELINE_DAYS_AGO)
    baseline_snapshot = queries.get_receivables_snapshot(db, organization_id, as_of=baseline_date)
    current_snapshot = queries.get_receivables_snapshot(db, organization_id, as_of=today_local)
    for code, (_, current_overdue) in current_snapshot.items():
        _, baseline_overdue = baseline_snapshot.get(code, (Decimal("0"), Decimal("0")))
        if (
            current_overdue > OVERDUE_SPIKE_MIN_ABSOLUTE
            and baseline_overdue > 0
            and current_overdue > baseline_overdue * OVERDUE_SPIKE_MULTIPLIER
        ):
            flags.append(
                AnomalyFlag(
                    rule="overdue_spike",
                    severity="high",
                    currency_code=code,
                    sample_size=1,
                    evidence=(
                        f"Overdue receivables rose from {baseline_overdue} to {current_overdue} {code} "
                        f"in the last {OVERDUE_SPIKE_BASELINE_DAYS_AGO} days."
                    ),
                )
            )

    # large_invoice -- any currently-open invoice far above this month's average.
    analytics = AnalyticsService(db=db, organization_id=organization_id)
    this_month = resolve_time_window(TimeWindowKind.current_month, organization=organization, now=now)
    avg_invoice_value = analytics.average_invoice_value(window=this_month)
    for inv in queries.get_open_invoices(db, organization_id):
        avg = avg_invoice_value.get(inv.currency_code)
        if avg and avg > 0 and inv.total > avg * LARGE_INVOICE_MULTIPLIER:
            flags.append(
                AnomalyFlag(
                    rule="large_invoice",
                    severity="medium",
                    currency_code=inv.currency_code,
                    sample_size=1,
                    evidence=(
                        f"Invoice #{inv.invoice_number} ({inv.total} {inv.currency_code}) is more than "
                        f"{LARGE_INVOICE_MULTIPLIER}x this month's average invoice value "
                        f"({quantize_money(avg)} {inv.currency_code})."
                    ),
                )
            )

    # customer_concentration -- top customer's share of all-time revenue.
    revenue_rows = queries.get_customer_revenue_all(db, organization_id)
    totals_by_currency: dict[str, Decimal] = {}
    rows_by_currency: dict[str, list] = {}
    for row in revenue_rows:
        rows_by_currency.setdefault(row.currency_code, []).append(row)
        totals_by_currency[row.currency_code] = totals_by_currency.get(row.currency_code, Decimal("0")) + row.revenue
    for code, rows in rows_by_currency.items():
        total = totals_by_currency[code]
        if total <= 0 or len(rows) < 2:
            continue
        top = max(rows, key=lambda r: r.revenue)
        share = (top.revenue / total * 100).quantize(PERCENT_QUANTIZE)
        if share >= CONCENTRATION_MEDIUM_THRESHOLD:
            severity = "high" if share >= CONCENTRATION_HIGH_THRESHOLD else "medium"
            flags.append(
                AnomalyFlag(
                    rule="customer_concentration",
                    severity=severity,
                    currency_code=code,
                    sample_size=len(rows),
                    evidence=f"{top.customer_name} accounts for {share}% of {code} revenue.",
                )
            )

    return AnomaliesResponse(generated_at=now, plan_restricted=False, flags=flags)


# --- 6. Forecast summary (compact, cross-section headline) --------------


def build_forecast_summary_section(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> ForecastSummaryResponse:
    now = now or datetime.now(timezone.utc)
    caps = get_organization_capabilities(db, organization_id)
    if not can_use_revenue_forecasting(caps):
        return ForecastSummaryResponse(generated_at=now, plan_restricted=True, results=[])

    revenue = build_revenue_forecast_section(db, organization_id, now=now)
    collections = build_collections_forecast_section(db, organization_id, now=now)
    anomalies = build_anomalies_section(db, organization_id, now=now)

    collections_by_code = {r.currency_code: r for r in collections.results}
    per_currency_anomaly_count: dict[str, int] = {}
    global_anomaly_count = 0
    for flag in anomalies.flags:
        if flag.currency_code:
            per_currency_anomaly_count[flag.currency_code] = per_currency_anomaly_count.get(flag.currency_code, 0) + 1
        else:
            global_anomaly_count += 1

    results: list[ForecastSummaryCurrencyResult] = []
    for r in revenue.results:
        revenue_90d = next((h for h in r.horizons if h.horizon_days == 90), None)
        collections_result = collections_by_code.get(r.currency_code)
        collections_90d = (
            next((h for h in collections_result.horizons if h.horizon_days == 90), None)
            if collections_result
            else None
        )
        results.append(
            ForecastSummaryCurrencyResult(
                currency_code=r.currency_code,
                model=r.model,
                confidence=r.confidence,
                revenue_90d=revenue_90d,
                collections_90d=collections_90d,
                anomaly_count=per_currency_anomaly_count.get(r.currency_code, 0) + global_anomaly_count,
            )
        )

    return ForecastSummaryResponse(generated_at=now, plan_restricted=False, results=results)


# --- 7. Scenario analysis --------------------------------------------------


def evaluate_scenario(
    db: Session,
    organization_id: str,
    *,
    scenario: ScenarioName = "base",
    assumptions: ScenarioAssumptions | None = None,
    now: datetime | None = None,
) -> ScenarioResponse:
    """Re-runs the same deterministic forecast math with user-adjustable
    multipliers layered on top -- NEVER re-queries or mutates stored
    business data; only the already-fetched history/open-invoice
    snapshot is transformed arithmetically. `invoice_growth_percent`
    compounds per month-ahead (month k's forecast is scaled by
    (1 + growth/100)^k); `collection_delay_days` shifts the organization-
    wide payment-delay average used for the "known" collections
    component (a scenario deliberately uses the SIMPLER org-wide-only
    delay path, not the customer-aware refinement in
    _known_collections_by_horizon, since a what-if toggle is about one
    adjustable assumption, not per-customer precision);
    quote_conversion_delta_percent scales the historical collection rate
    applied to projected (not-yet-invoiced) future revenue."""
    now = now or datetime.now(timezone.utc)
    caps = get_organization_capabilities(db, organization_id)
    used_assumptions = assumptions if assumptions is not None else SCENARIO_PRESETS[scenario]
    if not can_use_revenue_forecasting(caps):
        return ScenarioResponse(
            generated_at=now, plan_restricted=True, scenario=scenario, assumptions_used=used_assumptions, results=[]
        )

    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    histories = _currency_histories(db, organization_id, now=now)
    org_delay = cashflow.compute_payment_delay_stats(db, organization_id)
    adjusted_delay = _shift_delay(org_delay, used_assumptions.collection_delay_days)
    known_by_horizon = _known_collections_by_horizon(
        db, organization_id, today_local=today_local, horizon_days_list=COLLECTIONS_HORIZON_DAYS,
        org_delay=adjusted_delay,
    )
    growth_multiplier = Decimal("1") + used_assumptions.invoice_growth_percent / Decimal("100")
    conversion_multiplier = Decimal("1") + used_assumptions.quote_conversion_delta_percent / Decimal("100")
    max_months = max(HORIZON_MONTHS.values())

    results: list[ScenarioCurrencyResult] = []
    for code in sorted(histories):
        history = histories[code]
        method, evaluations = select_best_model(history.invoiced)
        revenue_horizons: list[HorizonForecast] = []
        collections_horizons: list[CollectionsHorizonResult] = []

        if method is not None:
            selected_wape = next(e.wape for e in evaluations if e.method == method)
            base_forecast = models.forecast_with(method, history.invoiced, steps=max_months)
            adjusted_values = [
                quantize_money(value * (growth_multiplier ** (index + 1)))
                for index, value in enumerate(base_forecast.values)
            ]

            invoiced_total = sum(history.invoiced, Decimal("0"))
            collection_rate = (
                (sum(history.collected, Decimal("0")) / invoiced_total) if invoiced_total > 0 else None
            )
            if collection_rate is not None:
                collection_rate = max(
                    Decimal("0"), min(collection_rate * conversion_multiplier, Decimal("1"))
                )

            for horizon_days in REVENUE_HORIZON_DAYS:
                if horizon_days == 365 and len(history.invoiced) < MIN_HISTORY_FOR_365D_HORIZON:
                    continue
                month_count = HORIZON_MONTHS[horizon_days]
                cumulative = quantize_money(sum(adjusted_values[:month_count], Decimal("0")))
                lower, upper = confidence_interval(cumulative, wape=selected_wape, steps_ahead=month_count)
                revenue_horizons.append(
                    HorizonForecast(
                        horizon_days=horizon_days, forecast_value=cumulative, lower_bound=lower, upper_bound=upper
                    )
                )

            for horizon_days in COLLECTIONS_HORIZON_DAYS:
                month_count = HORIZON_MONTHS[horizon_days]
                known = known_by_horizon[horizon_days].get(code, Decimal("0"))
                projected = (
                    quantize_money(sum(adjusted_values[:month_count], Decimal("0")) * collection_rate)
                    if collection_rate is not None
                    else Decimal("0")
                )
                total = quantize_money(known + projected)
                lower, upper = confidence_interval(total, wape=selected_wape, steps_ahead=month_count)
                collections_horizons.append(
                    CollectionsHorizonResult(
                        horizon_days=horizon_days,
                        known_amount=quantize_money(known),
                        projected_amount=projected,
                        total_expected=total,
                        lower_bound=lower,
                        upper_bound=upper,
                    )
                )

        results.append(
            ScenarioCurrencyResult(
                currency_code=code, revenue_horizons=revenue_horizons, collections_horizons=collections_horizons
            )
        )

    return ScenarioResponse(
        generated_at=now, plan_restricted=False, scenario=scenario, assumptions_used=used_assumptions, results=results
    )
