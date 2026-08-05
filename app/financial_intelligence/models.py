"""Phase 24.2 -- the deterministic forecast model library.

Every function here takes a chronological (oldest-first) `list[Decimal]`
monthly series and a `steps` count, and returns a `ModelForecast`: one
predicted value per future month, always reproducible by hand from the
same history and the model's own name -- no machine learning, no
external statistics package, no hidden state. This mirrors
app.analytics.forecast's existing "no complex statistical packages,
every number explainable" discipline, extended here to multi-step
(months-ahead) forecasts rather than that module's single-period-ahead
scope, since app.analytics.forecast's own signature (one value out) can't
express "give me a value for each of the next 6 months" that
forecasting.py's horizon-based sections need.

Four candidate models, each with its own honest eligibility floor
(MIN_HISTORY[method]) -- backtesting.py never lets a model "vote" for
selection unless the organization's real history clears this floor:

- seasonal_naive: month M's forecast = the value from the same calendar
  month one season (12 months) back, cycling for steps > 12. Captures a
  recurring yearly pattern (e.g. a December spike) that the other three
  models cannot see at all. Needs a full season of history to be
  justified.
- rolling_average: the plain average of the last `window` months,
  repeated flat for every future step. Smooths noise, lags a real trend.
- weighted_moving_average: same window, linearly increasing weights
  (recent months count more) -- reduces that lag while staying just as
  reproducible by hand.
- linear_trend: ordinary least squares through the FULL history,
  extrapolated `steps` points ahead -- the only model whose forecast
  genuinely changes shape over the horizon (the other three are flat or
  repeating), at the cost of being pulled by a single volatile month.

None of these "detect" a one-off event or a signed contract -- they are
pure extrapolations of past values, same as app.analytics.forecast's own
disclaimer.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.analytics.primitives import quantize_money

DEFAULT_WINDOW = 3
SEASON_LENGTH = 12

# The minimum number of historical monthly observations required for a
# model's forecast to be considered justified at all -- below this, the
# model is not merely "less accurate," it is not computable/meaningful,
# so backtesting.py excludes it from model selection entirely rather
# than silently returning a low-confidence number from it.
MIN_HISTORY: dict[str, int] = {
    "rolling_average": 2,
    "weighted_moving_average": 2,
    "linear_trend": 2,
    # A single season plus one more point, so at least one rolling-origin
    # backtest fold (train on one season, hold out the next real point)
    # is possible -- a bare 12 points could compute a seasonal_naive
    # VALUE but could never be genuinely VALIDATED against real history.
    "seasonal_naive": SEASON_LENGTH + 1,
}


class ForecastModelName(str, Enum):
    seasonal_naive = "seasonal_naive"
    rolling_average = "rolling_average"
    weighted_moving_average = "weighted_moving_average"
    linear_trend = "linear_trend"


@dataclass(frozen=True)
class ModelForecast:
    """`available=False` is an honest gap (history below this model's own
    MIN_HISTORY floor), never a fabricated `values` list standing in for
    missing data -- same pattern app.analytics.forecast.Forecast already
    established for its single-period case."""

    available: bool
    method: ForecastModelName
    values: list[Decimal]
    reason: str | None


def _unavailable(method: ForecastModelName, *, needed: int, have: int) -> ModelForecast:
    return ModelForecast(
        available=False,
        method=method,
        values=[],
        reason=f"Needs at least {needed} historical months; only {have} on file.",
    )


def rolling_average(history: list[Decimal], *, steps: int, window: int = DEFAULT_WINDOW) -> ModelForecast:
    method = ForecastModelName.rolling_average
    if len(history) < MIN_HISTORY[method.value]:
        return _unavailable(method, needed=MIN_HISTORY[method.value], have=len(history))
    used = history[-window:] if window > 0 else history
    average = quantize_money(sum(used, Decimal("0")) / Decimal(len(used)))
    return ModelForecast(available=True, method=method, values=[average] * steps, reason=None)


def weighted_moving_average(
    history: list[Decimal], *, steps: int, window: int = DEFAULT_WINDOW
) -> ModelForecast:
    method = ForecastModelName.weighted_moving_average
    if len(history) < MIN_HISTORY[method.value]:
        return _unavailable(method, needed=MIN_HISTORY[method.value], have=len(history))
    used = history[-window:] if window > 0 else history
    weights = list(range(1, len(used) + 1))
    weighted_sum = sum((value * weight for value, weight in zip(used, weights)), Decimal("0"))
    weighted_average = quantize_money(weighted_sum / Decimal(sum(weights)))
    return ModelForecast(available=True, method=method, values=[weighted_average] * steps, reason=None)


def _linear_regression_forecast(values: list[float], *, steps: int) -> list[float]:
    """Ordinary least squares over x = 0..n-1, y = values, returning the
    fitted line's value at x = n, n+1, ..., n+steps-1 -- the multi-step
    generalization of app.analytics.forecast._linear_regression_next
    (which only ever returns the single x = n point). Same closed-form
    OLS, no library."""
    n = len(values)
    xs = list(range(n))
    sum_x = sum(xs)
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in zip(xs, values))
    sum_xx = sum(x * x for x in xs)

    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0:
        # Only possible when n == 1, already excluded by MIN_HISTORY.
        return [values[-1]] * steps
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    return [slope * (n + i) + intercept for i in range(steps)]


def linear_trend(history: list[Decimal], *, steps: int) -> ModelForecast:
    method = ForecastModelName.linear_trend
    if len(history) < MIN_HISTORY[method.value]:
        return _unavailable(method, needed=MIN_HISTORY[method.value], have=len(history))
    forecasts = _linear_regression_forecast([float(v) for v in history], steps=steps)
    # Never forecast negative revenue -- a steep downward line extrapolated
    # far enough would otherwise cross zero, which is not a meaningful
    # "negative revenue" prediction for this domain.
    values = [quantize_money(Decimal(str(max(v, 0.0)))) for v in forecasts]
    return ModelForecast(available=True, method=method, values=values, reason=None)


def seasonal_naive(
    history: list[Decimal], *, steps: int, season_length: int = SEASON_LENGTH
) -> ModelForecast:
    """Forecast for the k-th future month = the value from
    `season_length` months before it, reading forward from history where
    needed (a forecast more than one season out reuses an already-
    forecasted point from earlier in this same call, cycling through one
    season's shape repeatedly) -- the only model here that can express
    "this month is always higher than the others" (e.g. a December
    spike)."""
    method = ForecastModelName.seasonal_naive
    if len(history) < MIN_HISTORY[method.value]:
        return _unavailable(method, needed=MIN_HISTORY[method.value], have=len(history))
    extended = list(history)
    for i in range(steps):
        extended.append(extended[len(extended) - season_length])
    values = [quantize_money(v) for v in extended[len(history):]]
    return ModelForecast(available=True, method=method, values=values, reason=None)


MODEL_FUNCTIONS: dict[ForecastModelName, "callable"] = {
    ForecastModelName.seasonal_naive: seasonal_naive,
    ForecastModelName.rolling_average: rolling_average,
    ForecastModelName.weighted_moving_average: weighted_moving_average,
    ForecastModelName.linear_trend: linear_trend,
}


def forecast_with(method: ForecastModelName, history: list[Decimal], *, steps: int) -> ModelForecast:
    """Single dispatch entry point -- backtesting.py and forecasting.py
    call this rather than importing a specific model function, so adding
    a 5th candidate model later never requires touching call sites, only
    this table (mirrors app.analytics.forecast.forecast_next_period's
    identical role for the single-period forecaster)."""
    return MODEL_FUNCTIONS[method](history, steps=steps)


def eligible_models(history_length: int) -> list[ForecastModelName]:
    """Every candidate model genuinely justified by this much history --
    the list backtesting.select_best_model restricts itself to."""
    return [
        ForecastModelName(name) for name, minimum in MIN_HISTORY.items() if history_length >= minimum
    ]
