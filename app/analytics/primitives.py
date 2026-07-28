"""Shared metric primitives -- small, currency/money-shaped building blocks
reused across every calculator in app/analytics/calculators/, so each
calculator computes ITS OWN numbers but never reinvents money rounding or
growth-percent math on its own.

Deliberately minimal: this module holds primitives every calculator
genuinely needs (rounding, growth), not a speculative "generic metric
framework." Existing per-domain result shapes (ProductRevenue in
app.product_analytics, QuoteCurrencyPipeline in app.quote_analytics, ...)
are left exactly as they are -- retrofitting them onto a new wrapper type
would be a rewrite of working, tested code for no behavioral gain, which
is precisely what this phase's "extend, don't replace" instruction rules
out.
"""

from decimal import Decimal

MONEY_QUANTIZE = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    """Rounds a monetary amount to 2 decimal places -- the one place this
    happens, replacing the identical `_quantize_money` helper that used to
    be private to app.routers.dashboard (also reimplemented inline via
    `.quantize(Decimal("0.01"))` in app.quote_analytics). Every calculator
    that returns money calls this before returning, so a caller never has
    to re-round a value that came from this package."""
    return Decimal(value).quantize(MONEY_QUANTIZE)


def growth_percent(current: Decimal, previous: Decimal) -> Decimal | None:
    """The one canonical month-over-month (or window-over-window) growth
    formula in this codebase, replacing the identical calculation that
    used to be duplicated between app.routers.dashboard's revenue-growth
    figure and app.insights.engine's product-level growth insight (each
    reapplying the same `(this - last) / last * 100` by hand).

    Returns None when `previous` is zero or negative -- "growth" is
    undefined without a real prior baseline (a first month with revenue
    is not "infinite growth"; see the callers that special-case this
    exact return value as "first period with activity" rather than
    treating it as a data error).
    """
    if previous is None or previous <= 0:
        return None
    return ((current - previous) / previous * 100).quantize(MONEY_QUANTIZE)
