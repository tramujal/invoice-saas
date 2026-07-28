"""TrendDirection -- the one reusable UP/DOWN/FLAT/UNKNOWN vocabulary
every period comparison in this app classifies its percentage change
into. Introduced so a future caller (AI insights, a new report, a new
chart) reads a direction that's already been decided here, rather than
each one inventing its own "is this really flat?" threshold.

Deliberately just four values -- no "strongly up"/"slightly down"
gradient. A magnitude (percentage_difference on PeriodComparison) is
already available alongside direction for any caller that wants finer
severity buckets of its own (see app.insights.engine's own, differently-
tuned thresholds, which are a business-narrative concern this module has
no opinion on).
"""

from decimal import Decimal
from enum import Enum

# Below this absolute percentage, a change is noise, not a direction --
# e.g. +0.3% revenue between two months is not meaningfully "up," it's
# effectively flat. 1% is a small, conservative bar: large enough to
# swallow floating/rounding noise, small enough that any change a human
# would actually call "up" or "down" still clears it.
FLAT_THRESHOLD_PERCENT = Decimal("1")


class TrendDirection(str, Enum):
    up = "up"
    down = "down"
    flat = "flat"
    unknown = "unknown"


def direction_from_percent(
    percentage_difference: Decimal | float | None,
    *,
    flat_threshold: Decimal = FLAT_THRESHOLD_PERCENT,
) -> TrendDirection:
    """Classifies a percentage difference (current vs. previous) into a
    TrendDirection. `None` means "no previous baseline to compare
    against" (see app.analytics.primitives.growth_percent) -- genuinely
    unknown, not zero change, so it must never collapse to `flat`."""
    if percentage_difference is None:
        return TrendDirection.unknown
    value = Decimal(str(percentage_difference))
    if abs(value) < flat_threshold:
        return TrendDirection.flat
    return TrendDirection.up if value > 0 else TrendDirection.down
