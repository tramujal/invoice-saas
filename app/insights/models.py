"""Internal representation of a dashboard insight.

Kept as plain dataclasses, separate from the API-facing Pydantic schemas
in app/schemas.py, so the deterministic engine has no FastAPI/Pydantic
dependency and its ranking-only fields (never serialized) can't leak into
the API response by accident.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class InsightSeverity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"
    positive = "positive"


class InsightCategory(str, Enum):
    revenue = "revenue"
    overdue = "overdue"
    due_soon = "due_soon"
    pending = "pending"
    concentration = "concentration"
    inactivity = "inactivity"
    volume = "volume"
    status_distribution = "status_distribution"
    new_business = "new_business"
    multi_currency = "multi_currency"
    data_quality = "data_quality"


# Higher = shown first. "positive" ranks above plain "info" since a strong
# positive result is still worth surfacing prominently, not just a neutral
# observation.
SEVERITY_RANK: dict[InsightSeverity, int] = {
    InsightSeverity.critical: 4,
    InsightSeverity.warning: 3,
    InsightSeverity.positive: 2,
    InsightSeverity.info: 1,
}


@dataclass
class InsightMetric:
    currency_code: str | None
    value: Decimal | None
    percentage: float | None


@dataclass
class InsightRelatedEntity:
    type: str | None  # "invoice" | "customer" | None
    id: str | None
    label: str | None


@dataclass
class InsightCta:
    type: str  # "view_overdue_invoices" | "review_pending_invoices" | "create_invoice" | "ask_assistant"
    # Only set for type == "ask_assistant" -- a deterministic, backend-
    # rendered (already localized) prefill question. Never AI-generated.
    question: str | None = None


@dataclass
class Insight:
    id: str
    category: InsightCategory
    severity: InsightSeverity
    title: str
    message: str
    suggestion: str | None
    metric: InsightMetric | None
    related_entity: InsightRelatedEntity | None
    cta: InsightCta | None
    # Ranking-only -- combines severity (primary key) with a 0-999
    # category-specific magnitude (tiebreaker); never serialized to the API.
    priority_score: float = 0.0
