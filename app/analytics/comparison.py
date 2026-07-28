"""PeriodComparison -- the one reusable "current vs. previous" shape
every trend calculator in app.analytics.calculators.trends builds its
result from. Exposes more than a bare percentage on purpose (see this
phase's own spec: "Do not expose only percentages") -- current, previous,
and the absolute difference are each independently useful to a caller
that wants to render "$1,200 -> $1,450 (+$250, +20.8%, up)" rather than
just "+20.8%".

Works uniformly over both money (Decimal revenue) and counts (invoice/
customer/quote counts, cast to Decimal by the caller) -- one shape, not a
money variant and a separate count variant, per this phase's "create a
reusable representation" instruction.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.analytics.primitives import growth_percent, quantize_money
from app.analytics.trend_direction import TrendDirection, direction_from_percent


@dataclass(frozen=True)
class PeriodComparison:
    current: Decimal
    previous: Decimal
    absolute_difference: Decimal
    percentage_difference: Decimal | None
    direction: TrendDirection


def compare_periods(current: Decimal, previous: Decimal) -> PeriodComparison:
    """Builds a PeriodComparison from two already-computed values -- this
    function does no querying itself; every calculator in
    app.analytics.calculators.trends calls it after fetching `current` and
    `previous` from the same per-metric calculators Phase 16A already
    built (get_revenue_by_currency, get_invoice_counts, ...), so the
    trend engine never recomputes a metric's own value, only compares two
    values someone else already computed correctly."""
    percentage_difference = growth_percent(current, previous)
    return PeriodComparison(
        current=quantize_money(current),
        previous=quantize_money(previous),
        absolute_difference=quantize_money(current - previous),
        percentage_difference=percentage_difference,
        direction=direction_from_percent(percentage_difference),
    )
