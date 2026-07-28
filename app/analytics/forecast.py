"""Deterministic short-term forecasting -- projects ONE period ahead from
a currency-specific (or count-based) historical series, using only plain
arithmetic. No machine learning, no external statistics package, no
external API calls: every number a caller sees here can be reproduced by
hand from the `inputs`/`method`/`window_size` this module returns
alongside it, per this phase's "every forecast must explain how it was
calculated" requirement -- deliberately structured data (inputs + method),
not a generated prose sentence, so the frontend can render its own
translated explanation rather than displaying an English sentence
verbatim (the same reasoning
app.analytics.calculators.payments.AveragePaymentTime's `reason` field
documents: an internal-facing string is not end-user copy).

Algorithm choices (see this phase's completion report for the fuller
tradeoff discussion):
- simple_moving_average: the average of the last `window` periods.
  Simplest to explain, smooths out noise, but lags a real trend (a
  business accelerating every month still gets a forecast pulled toward
  its older, lower months).
- weighted_moving_average: same window, but recent periods count more
  (linearly increasing weights 1..window) -- reduces that lag while
  staying just as explainable (the weights are exposed, not hidden).
- linear_trend: fits a straight line through the ENTIRE available history
  (ordinary least squares, computed by hand -- see _linear_regression
  below) and extrapolates one period forward. Captures directional
  momentum explicitly, at the cost of being more sensitive to a single
  volatile period (an outlier pulls the whole line, where a moving
  average would only pull one term of its average).

None of the three methods "detects seasonality" or accounts for known
future changes (a signed contract, a planned price increase) -- they are
pure extrapolations of past values, which is exactly what "deterministic
short-term forecasting foundations" (not a predictive model) means here.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.analytics.primitives import quantize_money

DEFAULT_WINDOW = 3
MIN_HISTORY_FOR_FORECAST = 2

NOT_ENOUGH_HISTORY_REASON = (
    "At least 2 historical periods are required to compute a forecast; "
    "fewer would be extrapolating from a single data point."
)


class ForecastMethod(str, Enum):
    simple_moving_average = "simple_moving_average"
    weighted_moving_average = "weighted_moving_average"
    linear_trend = "linear_trend"


@dataclass(frozen=True)
class Forecast:
    """`available=False` is an honest gap (not enough history yet), the
    same pattern app.analytics.calculators.payments.AveragePaymentTime
    already established -- never a fabricated forecast_value standing in
    for missing data. `inputs` is always the exact historical values this
    forecast was computed from, in order -- the transparency this
    module's whole design is built around."""

    available: bool
    method: ForecastMethod | None
    forecast_value: Decimal | None
    inputs: list[Decimal]
    window_size: int | None
    reason: str | None


def _unavailable(inputs: list[Decimal]) -> Forecast:
    return Forecast(
        available=False,
        method=None,
        forecast_value=None,
        inputs=inputs,
        window_size=None,
        reason=NOT_ENOUGH_HISTORY_REASON,
    )


def forecast_simple_moving_average(history: list[Decimal], *, window: int = DEFAULT_WINDOW) -> Forecast:
    """Forecast = plain average of the last `min(window, len(history))`
    values. Using fewer than `window` values (rather than refusing) when
    history is short but still >= MIN_HISTORY_FOR_FORECAST keeps this
    usable for a young organization with only 2-3 months on record."""
    if len(history) < MIN_HISTORY_FOR_FORECAST:
        return _unavailable(history)
    used = history[-window:] if window > 0 else history
    average = sum(used, Decimal("0")) / len(used)
    return Forecast(
        available=True,
        method=ForecastMethod.simple_moving_average,
        forecast_value=quantize_money(average),
        inputs=used,
        window_size=len(used),
        reason=None,
    )


def forecast_weighted_moving_average(history: list[Decimal], *, window: int = DEFAULT_WINDOW) -> Forecast:
    """Forecast = weighted average of the last `min(window, len(history))`
    values, weights 1..N assigned oldest-to-newest within that slice (the
    most recent period gets the largest weight) -- reduces the lag a
    plain moving average has behind a genuinely accelerating or
    decelerating trend, while remaining just as reproducible by hand as
    the simple average (the weights themselves are deterministic, not
    fitted)."""
    if len(history) < MIN_HISTORY_FOR_FORECAST:
        return _unavailable(history)
    used = history[-window:] if window > 0 else history
    weights = list(range(1, len(used) + 1))
    weighted_sum = sum((value * weight for value, weight in zip(used, weights)), Decimal("0"))
    weighted_average = weighted_sum / Decimal(sum(weights))
    return Forecast(
        available=True,
        method=ForecastMethod.weighted_moving_average,
        forecast_value=quantize_money(weighted_average),
        inputs=used,
        window_size=len(used),
        reason=None,
    )


def _linear_regression_next(values: list[float]) -> float:
    """Ordinary least squares over x = 0..n-1, y = values, returning the
    fitted line's value at x = n (one step past the last observed point).
    Plain closed-form OLS (no library): slope = (n*Sxy - Sx*Sy) /
    (n*Sxx - Sx**2), intercept = (Sy - slope*Sx) / n. Deliberately hand-
    rolled rather than importing `statistics.linear_regression` (Python
    3.10+) or numpy/scipy, per this phase's "no complex statistical
    packages" constraint -- five lines of closed-form arithmetic needs no
    dependency and is exactly as easy to verify by hand as the moving
    averages above."""
    n = len(values)
    xs = list(range(n))
    sum_x = sum(xs)
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in zip(xs, values))
    sum_xx = sum(x * x for x in xs)

    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0:
        # Only possible when n == 1, already excluded by
        # MIN_HISTORY_FOR_FORECAST -- guarded anyway so this never raises.
        return values[-1]
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    return slope * n + intercept


def forecast_linear_trend(history: list[Decimal]) -> Forecast:
    """Forecast = the best-fit straight line through the FULL history,
    extrapolated one period forward. Unlike the two moving averages,
    every historical point is used (window_size is always None here) --
    there is no "last N periods" cutoff to choose."""
    if len(history) < MIN_HISTORY_FOR_FORECAST:
        return _unavailable(history)
    forecast_float = _linear_regression_next([float(value) for value in history])
    return Forecast(
        available=True,
        method=ForecastMethod.linear_trend,
        forecast_value=quantize_money(Decimal(str(forecast_float))),
        inputs=history,
        window_size=None,
        reason=None,
    )


def forecast_next_period(
    history: list[Decimal], *, method: ForecastMethod = ForecastMethod.simple_moving_average, window: int = DEFAULT_WINDOW
) -> Forecast:
    """Single dispatch entry point -- every caller (AnalyticsService, the
    /analytics/trends route) goes through this rather than importing a
    specific forecast_* function, so adding a 4th deterministic method
    later never requires touching call sites, only this dispatch table."""
    if method == ForecastMethod.simple_moving_average:
        return forecast_simple_moving_average(history, window=window)
    if method == ForecastMethod.weighted_moving_average:
        return forecast_weighted_moving_average(history, window=window)
    if method == ForecastMethod.linear_trend:
        return forecast_linear_trend(history)
    raise ValueError(f"Unhandled ForecastMethod: {method}")
