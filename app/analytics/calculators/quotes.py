"""Thin analytics-layer wrapper around app.quote_analytics -- quote
conversion/acceptance-rate is already computed by
get_quote_pipeline_summary; this module re-exposes the one figure the KPI
engine cares about under the analytics calculator namespace rather than
recomputing it.
"""

from sqlalchemy.orm import Session

from app.quote_analytics import (
    QuoteMonthlyConversion,
    QuotePipelineData,
    get_quote_monthly_conversions,
    get_quote_pipeline_summary,
)

__all__ = [
    "QuoteMonthlyConversion",
    "QuotePipelineData",
    "get_quote_pipeline",
    "get_quote_monthly_conversion_series",
    "get_quote_acceptance_rate",
]


def get_quote_pipeline(db: Session, organization_id: str) -> QuotePipelineData:
    """Full pipeline snapshot (counts by status, acceptance rate, per-
    currency figures) -- delegates entirely to
    app.quote_analytics.get_quote_pipeline_summary, re-exposed here so
    AnalyticsService has one consistent import surface across every
    domain instead of reaching into app.quote_analytics directly for this
    one call while going through app.analytics.calculators for
    everything else."""
    return get_quote_pipeline_summary(db, organization_id)


def get_quote_monthly_conversion_series(db, organization_id: str, month_starts):
    """Converted-quote counts per month -- delegates to
    app.quote_analytics.get_quote_monthly_conversions."""
    return get_quote_monthly_conversions(db, organization_id, month_starts)


def get_quote_acceptance_rate(db: Session, organization_id: str) -> float | None:
    """Acceptance rate = accepted / (accepted + rejected), all-time --
    delegates entirely to app.quote_analytics.get_quote_pipeline_summary,
    the existing single source of truth for quote-pipeline figures. See
    that module for why this is all-time (quotes don't carry a separate
    decided_at column to window by)."""
    return get_quote_pipeline_summary(db, organization_id).acceptance_rate_percent
