"""Phase 24.3 -- the AI Financial Advisor's strict output schema.

This is the ONLY place the model's structured reply shape is defined.
app.financial_intelligence.recommendations validates every response
against FinancialAnalysisPayload before it is ever persisted or shown --
a response that fails this validation is treated exactly like a provider
failure (retried once, then recorded as a failed report), never partially
trusted or exposed. `model_config = ConfigDict(extra="forbid")` on every
model here means an unexpected field anywhere in the response invalidates
the whole payload, the same "no partial trust" discipline
app.insights.narration already established for its own, much smaller,
schema.

Every free-text field has a bounded max_length -- both a UX bound and a
defensive ceiling against a model dumping something adversarially long,
matching app.insights.limits' INSIGHTS_MAX_TITLE_LENGTH-style precedent.
"""

from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.financial_report_status import FinancialReportStatus

MAX_SHORT_TEXT = 160
MAX_MEDIUM_TEXT = 500
MAX_LONG_TEXT = 900
MAX_EVIDENCE_TEXT = 200
MAX_LIST_ITEM_TEXT = 220

ShortText = Annotated[str, Field(min_length=1, max_length=MAX_SHORT_TEXT)]
MediumText = Annotated[str, Field(min_length=1, max_length=MAX_MEDIUM_TEXT)]
ListItemText = Annotated[str, Field(min_length=1, max_length=MAX_LIST_ITEM_TEXT)]


class ObservationCategory(str, Enum):
    revenue = "revenue"
    collections = "collections"
    cash_flow = "cash_flow"
    forecast = "forecast"
    customers = "customers"
    products = "products"
    quotes = "quotes"
    growth = "growth"
    risk = "risk"
    anomalies = "anomalies"
    data_quality = "data_quality"


class ObservationSeverity(str, Enum):
    info = "info"
    positive = "positive"
    warning = "warning"
    critical = "critical"


class RecommendationPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class OverallHealth(str, Enum):
    excellent = "excellent"
    good = "good"
    fair = "fair"
    poor = "poor"
    critical = "critical"


class EvidenceItem(BaseModel):
    """One cited fact backing an observation -- always a label naming
    WHICH metric, and the exact value from that metric (as already
    formatted in the structured context handed to the model). Never a
    number the model computed itself; see app.financial_intelligence
    .insight_builder for the only source of truth these values may come
    from."""

    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, Field(min_length=1, max_length=MAX_EVIDENCE_TEXT)]
    value: Annotated[str, Field(min_length=1, max_length=MAX_EVIDENCE_TEXT)]


class Observation(BaseModel):
    """No observation may exist without evidence -- `evidence` requires
    at least one item, enforced here, not left to the prompt alone."""

    model_config = ConfigDict(extra="forbid")

    category: ObservationCategory
    severity: ObservationSeverity
    title: ShortText
    explanation: MediumText
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=6)


class Recommendation(BaseModel):
    """Every recommendation must reference real metrics (via `reason`,
    expected to name the evidence backing it) and acknowledge uncertainty
    (via `limitations`) -- both required, non-empty fields, never
    optional escape hatches the model can skip."""

    model_config = ConfigDict(extra="forbid")

    priority: RecommendationPriority
    title: ShortText
    action: MediumText
    reason: MediumText
    expected_impact: MediumText
    limitations: MediumText


class FinancialAnalysisPayload(BaseModel):
    """The complete, strictly-validated AI Financial Advisor report.
    Every field is required and bounded -- there is no optional field a
    malformed response could omit to still pass validation, matching this
    phase's own "reject malformed responses" requirement exactly at the
    schema layer rather than via ad-hoc post-hoc checks.

    `observations` requires at least one entry (even an empty
    organization has an honest "not enough data yet" observation to make,
    in the data_quality category) -- `recommendations` does not, since a
    genuinely new organization may have nothing actionable to recommend
    yet, and forcing one would invite fabrication."""

    model_config = ConfigDict(extra="forbid")

    executive_summary: MediumText
    overall_health: OverallHealth
    confidence_notice: MediumText
    observations: list[Observation] = Field(min_length=1, max_length=10)
    recommendations: list[Recommendation] = Field(max_length=8)
    forecast_commentary: MediumText
    strengths: list[ListItemText] = Field(max_length=6)
    risks: list[ListItemText] = Field(max_length=6)
    opportunities: list[ListItemText] = Field(max_length=6)
    next_actions: list[ListItemText] = Field(max_length=6)
    disclaimer: MediumText


class InsightReportResponse(BaseModel):
    """The API-facing view of one FinancialInsightReport row --
    `analysis` is populated (parsed back from the persisted JSON) only
    when `status == completed`; it is always None while pending or
    failed, never a partial/best-effort payload. `reused` is only
    meaningful on the POST .../insights/generate response: True means an
    existing completed, unexpired report for the same underlying data was
    returned directly, no new AI call was made."""

    id: str
    status: FinancialReportStatus
    period_start: date
    period_end: date
    ai_provider: str | None
    ai_model: str | None
    generated_at: datetime | None
    expires_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_by_user_id: str | None
    created_at: datetime
    analysis: FinancialAnalysisPayload | None
    reused: bool = False
