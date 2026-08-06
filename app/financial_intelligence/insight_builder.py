"""Phase 24.3 -- builds the ONE deterministic, PII-minimal structured
context object the AI Financial Advisor is ever shown.

Every field here is copied from a value app.financial_intelligence.metrics
/ forecasting already computed and validated in Phase 24.1/24.2 -- this
module never queries the database itself, never computes a number of its
own, and never lets the AI calculate a total (per this phase's own
"the AI must only interpret deterministic metrics" constraint). The
response shapes it dumps (ExecutiveOverviewResponse, CustomersSectionResponse,
ProductsSectionResponse, ...) are already PII-minimal by Phase 24.1's own
design -- customer/product entries carry only id/name/currency/numeric
aggregates, never email, phone, address, notes, or raw invoice text -- so
no additional stripping is needed here, only reserialization to a JSON-
safe, stable shape.

The returned dict is used for two purposes: rendered into the prompt
(see prompt_builder.render_context_text) and fingerprinted (see
cache.compute_source_fingerprint) to decide whether an existing report is
still fresh. Both purposes need the SAME data, which is exactly why this
function exists as a single, shared builder rather than two ad hoc call
sites duplicating the same 10 builder calls.
"""

from dataclasses import is_dataclass, asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.financial_intelligence import forecasting, metrics


def _json_safe(value: Any) -> Any:
    """Recursively converts a value (a Pydantic model, a dataclass, or any
    nested combination of dict/list/Decimal/date/datetime/Enum) into a
    plain, JSON-serializable structure with STABLE types -- Decimal and
    date/datetime become strings, Enum members become their `.value`.
    Applied uniformly so the fingerprint (cache.py) and the prompt text
    (prompt_builder.py) always see byte-for-byte the same representation
    of the same underlying data."""
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def build_structured_context(
    db: Session, organization_id: str, *, now: datetime | None = None
) -> dict:
    """Assembles the full deterministic context in one call -- 10 builder
    calls total, each already a small, bounded number of SQL queries (see
    each module's own performance notes); nothing here adds a query of
    its own. Deliberately flat and explicitly-keyed (never a generic
    "dump everything" reflection over the response objects) so a future
    field added to one of those response models doesn't silently change
    what the AI sees without a deliberate decision here."""
    now = now or datetime.now(timezone.utc)

    overview = metrics.build_executive_overview(db, organization_id, now=now)
    trends = metrics.build_revenue_trends_section(db, organization_id, now=now)
    aging = metrics.build_receivables_section(db, organization_id, now=now)
    customers = metrics.build_customers_section(db, organization_id, now=now)
    products = metrics.build_products_section(db, organization_id, now=now)
    quotes = metrics.build_quotes_section(db, organization_id, now=now)

    revenue_forecast = forecasting.build_revenue_forecast_section(db, organization_id, now=now)
    collections_forecast = forecasting.build_collections_forecast_section(db, organization_id, now=now)
    forecast_accuracy = forecasting.build_forecast_accuracy_section(db, organization_id, now=now)
    anomalies = forecasting.build_anomalies_section(db, organization_id, now=now)

    context = {
        "generated_at": now,
        "period_start": overview.period_start,
        "period_end": overview.period_end,
        "executive_kpis_by_currency": overview.by_currency,
        "quote_conversion_rate": overview.quote_conversion_rate,
        "average_days_to_payment": overview.average_days_to_payment,
        "revenue_trends": trends,
        "receivables_aging": aging,
        "customers": customers,
        "products": products,
        "quotes_funnel": quotes,
        "revenue_forecast": revenue_forecast,
        "expected_collections": collections_forecast,
        "forecast_model_accuracy": forecast_accuracy,
        "detected_anomalies": anomalies.flags,
        # "scenario" is always "base" here -- the AI Advisor analyzes the
        # organization's REAL, unadjusted trajectory, never a
        # user-adjusted what-if scenario (Phase 24.2's Scenario Controls
        # are a separate, explicitly-labeled exploration tool, never fed
        # to the AI as if it were the real forecast).
        "scenario": "base",
    }
    return _json_safe(context)
