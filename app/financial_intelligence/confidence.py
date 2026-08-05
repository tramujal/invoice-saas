"""Phase 24.2 -- confidence classification and interval width.

Two honest, deterministic signals feed every forecast's confidence, never
a single opaque score:
1. How much real history backs it (`sample_size`) -- a forecast built
   from 3 months on file can never be "high confidence," no matter how
   well it happens to backtest, because 3 months is too small a sample
   to trust that backtest result itself.
2. How well the SELECTED model actually backtested (`wape` from
   app.financial_intelligence.backtesting) -- real historical accuracy,
   not a guess.

Confidence intervals widen with both a worse backtest WAPE and a longer
horizon (more months ahead = more compounding uncertainty) -- a
deliberately simple, reproducible-by-hand sqrt(steps) scaling, not a
statistical model of its own. This never claims false precision: a
12-month-ahead point forecast always carries a wider band than a
1-month-ahead one built from the identical history.
"""

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from math import sqrt

from app.analytics.primitives import quantize_money

# Below this many real monthly observations, there is not enough history
# to trust ANY forecast at all -- app.financial_intelligence.models'
# smallest MIN_HISTORY floor (2) can technically produce a number, but 2
# points is not "low confidence," it is not yet a confidence-worthy
# forecast at all.
MIN_SAMPLE_INSUFFICIENT = 3
MIN_SAMPLE_MEDIUM = 6
MIN_SAMPLE_HIGH = 12

# Backtested WAPE thresholds -- a model whose own one-step-ahead
# historical error was already large has no business being labeled
# "high confidence" regardless of how much history produced it.
WAPE_HIGH_MAX = Decimal("15")
WAPE_MEDIUM_MAX = Decimal("35")

# Used only when a model is eligible but has zero backtest folds (exactly
# enough history to compute a value, one short of validating it) -- a
# deliberately wide, honest default rather than a false sense of
# precision from an unvalidated model.
UNVALIDATED_SPREAD_FRACTION = Decimal("0.50")


class ConfidenceLevel(str, Enum):
    insufficient_data = "insufficient_data"
    low = "low"
    medium = "medium"
    high = "high"


def classify_confidence(sample_size: int, wape: Decimal | None) -> ConfidenceLevel:
    """Sample size gates the CEILING a forecast can reach; backtest WAPE
    (when available) can only pull that ceiling down, never raise it
    above what the sample size alone would allow."""
    if sample_size < MIN_SAMPLE_INSUFFICIENT:
        return ConfidenceLevel.insufficient_data
    if sample_size < MIN_SAMPLE_MEDIUM:
        return ConfidenceLevel.low
    if wape is None:
        # Enough history to compute a value, but no real backtest fold to
        # validate it against yet -- stay at "low" rather than trust an
        # unvalidated model.
        return ConfidenceLevel.low
    if sample_size >= MIN_SAMPLE_HIGH and wape <= WAPE_HIGH_MAX:
        return ConfidenceLevel.high
    if wape <= WAPE_MEDIUM_MAX:
        return ConfidenceLevel.medium
    return ConfidenceLevel.low


def confidence_interval(
    point_value: Decimal, *, wape: Decimal | None, steps_ahead: int
) -> tuple[Decimal, Decimal]:
    """Returns (lower_bound, upper_bound) around `point_value`. Spread
    fraction = (wape / 100, or UNVALIDATED_SPREAD_FRACTION when there's no
    backtest yet) * sqrt(steps_ahead) -- growing with how far ahead this
    particular month/horizon sits, never a flat band applied uniformly
    regardless of distance into the future. Never lets the lower bound
    go negative -- revenue/collections cannot be negative."""
    base_fraction = (wape / 100) if wape is not None else UNVALIDATED_SPREAD_FRACTION
    spread_fraction = base_fraction * Decimal(str(sqrt(max(steps_ahead, 1))))
    # A floor and ceiling on the fraction itself: never a band so narrow
    # it implies false precision (min 5%), never so wide it's meaningless
    # (max 100%, i.e. lower bound of exactly 0).
    spread_fraction = max(Decimal("0.05"), min(spread_fraction, Decimal("1.00")))

    spread = (point_value * spread_fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    lower = quantize_money(max(point_value - spread, Decimal("0")))
    upper = quantize_money(point_value + spread)
    return lower, upper
