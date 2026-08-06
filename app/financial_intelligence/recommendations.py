"""Phase 24.3 -- the AI Financial Advisor. The ONLY module in the
Financial Intelligence package that talks to an AIProvider -- every
number it ever discusses is something app.financial_intelligence
.insight_builder already computed from real, deterministic data; this
module only sends that structured context to the model and strictly
validates the model's structured reply before anything is persisted or
shown to a user.

Flow (see this phase's own architecture requirement):
  deterministic metrics -> forecast -> structured context (insight_builder)
  -> prompt (prompt_builder) -> existing AIProvider (app.ai.factory)
  -> strict schema validation (schemas_ai.FinancialAnalysisPayload)
  -> FinancialInsightReport -> frontend.

On ANY failure -- disabled, unconfigured, timeout, provider error, no
tool call, or invalid schema -- the call is retried exactly ONCE more
(per this phase's own "reject malformed responses, retry once"
requirement); if the retry also fails, the report is recorded as
`failed` with a structured error code, never a fabricated or partial
result. An invalid/malformed model response is NEVER persisted or
exposed, matching app.insights.narration's own "no partial trust"
discipline for its much smaller schema.
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.base import AIProviderError, AIProviderTimeoutError, ChatMessage, ToolInvocation
from app.ai.factory import get_ai_provider
from app.analytics.time_windows import TimeWindowKind, resolve_time_window
from app.financial_intelligence import cache, insight_builder
from app.financial_intelligence.prompt_builder import (
    FINANCIAL_ADVISOR_SYSTEM_PROMPT,
    TOOL_NAME,
    build_tool_definition,
    render_context_text,
)
from app.financial_intelligence.schemas_ai import FinancialAnalysisPayload
from app.financial_report_status import FinancialReportStatus
from app.job_type import JobType
from app.models import FinancialInsightReport
from app.notifications.service import emit_event
from app.services.background_jobs import enqueue_job
from app.services.plan_limits import LimitedResource, check_limit
from app.webhook_event_type import WebhookEventType

logger = logging.getLogger(__name__)

# Longer than the assistant chat's default 30s (app.ai.limits
# .AI_REQUEST_TIMEOUT_SECONDS) -- this call sits in a background job, not
# a live chat the user is watching spin, and the context/expected output
# are both larger than an ordinary chat turn.
FINANCIAL_AI_TIMEOUT_SECONDS = float(os.environ.get("FINANCIAL_AI_TIMEOUT_SECONDS", "45"))

# One real attempt + one retry -- see this phase's own "retry once" requirement.
_MAX_ATTEMPTS = 2


def _call_model_once(context_text: str) -> FinancialAnalysisPayload:
    """One attempt end to end. Raises HTTPException (AI disabled/not
    configured), AIProviderTimeoutError, AIProviderError, ValueError (no
    tool call), or pydantic.ValidationError (schema mismatch) on any
    failure -- the caller decides whether to retry."""
    ai_provider = get_ai_provider(timeout_seconds=FINANCIAL_AI_TIMEOUT_SECONDS)
    tool = build_tool_definition()
    messages = [ChatMessage(role="user", content=context_text)]
    stream = ai_provider.stream_complete(FINANCIAL_ADVISOR_SYSTEM_PROMPT, messages, tools=[tool])

    invocation: ToolInvocation | None = None
    for event in stream:
        if isinstance(event, ToolInvocation) and event.name == TOOL_NAME:
            invocation = event
            break
        # Any TextDelta is silently discarded -- this is never shown to
        # the user as chat; only a valid tool call is a valid reply.

    if invocation is None:
        raise ValueError("model did not call the submit_financial_analysis tool")

    payload = FinancialAnalysisPayload.model_validate(invocation.arguments)
    provider_name = type(ai_provider).__name__.removesuffix("Provider").lower()
    model_name = getattr(ai_provider, "model", None)
    return payload, provider_name, model_name


def generate_analysis(
    context_text: str,
) -> tuple[FinancialAnalysisPayload | None, str | None, str | None, str | None, str | None]:
    """Returns (payload, provider, model, error_code, error_message).
    `payload` is None exactly when both attempts failed -- callers must
    treat that, and only that, as the failure signal (never inspect
    error_code alone to decide). Never raises."""
    error_code = "unknown_error"
    error_message = "Unknown error."

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            payload, provider_name, model_name = _call_model_once(context_text)
            return payload, provider_name, model_name, None, None
        except HTTPException as exc:
            error_code = "ai_unavailable"
            error_message = str(exc.detail)
        except AIProviderTimeoutError as exc:
            error_code = "provider_timeout"
            error_message = str(exc) or "The AI provider timed out."
        except AIProviderError as exc:
            error_code = "provider_error"
            error_message = str(exc) or "The AI provider failed."
        except (ValidationError, ValueError) as exc:
            error_code = "invalid_response"
            error_message = str(exc)

        logger.warning(
            "financial_intelligence.recommendations: attempt %d/%d failed error_code=%s",
            attempt,
            _MAX_ATTEMPTS,
            error_code,
        )

    return None, None, None, error_code, error_message[:500]


def request_insight_report(
    db: Session, organization_id: str, *, requested_by_user_id: str, force: bool = False
) -> tuple[FinancialInsightReport, bool]:
    """The one entry point app.financial_intelligence.service calls for
    POST .../insights/generate. Returns (report, reused) -- reused=True
    means an existing completed, unexpired report for the SAME
    fingerprint was returned directly, no new row created, no quota
    consumed, no AI call made (per "only regenerate when requested (and
    even then, only when nothing reusable exists), expired, or financial
    data changed" -- a plain repeated click against unchanged data is
    free). `force=True` (the Refresh Analysis button) always creates a
    fresh row and consumes one quota slot, regardless of whether an
    unexpired report already exists.

    Quota (LimitedResource.financial_ai_reports) is checked and consumed
    the moment a new row is created and a job enqueued for it -- matches
    app.services.organization_usage.count_financial_ai_reports_current_month's
    own documented "the cost is incurred at creation, not only on eventual
    success" convention."""
    now = datetime.now(timezone.utc)
    context = insight_builder.build_structured_context(db, organization_id, now=now)
    fingerprint = cache.compute_source_fingerprint(context)

    if not force:
        reusable = cache.find_reusable_report(db, organization_id, fingerprint, now=now)
        if reusable is not None:
            return reusable, True

    check_limit(db, organization_id, LimitedResource.financial_ai_reports)

    this_month = resolve_time_window(TimeWindowKind.current_month, now=now)
    report = FinancialInsightReport(
        organization_id=organization_id,
        status=FinancialReportStatus.pending.value,
        period_start=this_month.start.date(),
        period_end=this_month.end.date(),
        source_fingerprint=fingerprint,
        created_by_user_id=requested_by_user_id,
    )
    db.add(report)
    db.flush()

    enqueue_job(
        db,
        job_type=JobType.financial_insight_generate,
        payload={"report_id": report.id},
        organization_id=organization_id,
    )

    emit_event(
        db,
        organization_id=organization_id,
        event_type=WebhookEventType.financial_insight_requested,
        object_type="financial_insight_report",
        object_id=report.id,
        payload={"report_id": report.id, "forced": force},
        actor_user_id=requested_by_user_id,
    )
    db.commit()
    db.refresh(report)
    return report, False


def run_generation(db: Session, report_id: str) -> bool:
    """Called by app.jobs.handlers.financial_intelligence -- generates
    the analysis for one already-created, pending FinancialInsightReport
    row and commits its own outcome (business writes are this function's
    responsibility; the BackgroundJob row's own state is committed
    separately by app.services.background_jobs.complete_job, matching
    every other handler's two-commits convention -- see
    app.jobs.handlers.webhook's identical pattern).

    Returns True on success, False on a recorded (not raised) failure --
    either way the BACKGROUND JOB itself succeeded at doing its job
    (attempting generation and recording a definitive outcome); only a
    genuine unexpected exception should ever propagate out of this
    function to become a retryable job-execution failure."""
    report = db.get(FinancialInsightReport, report_id)
    if report is None:
        logger.warning("financial_intelligence.recommendations: report %s no longer exists", report_id)
        return False

    now = datetime.now(timezone.utc)
    context = insight_builder.build_structured_context(db, report.organization_id, now=now)
    context_text = render_context_text(context)

    payload, provider_name, model_name, error_code, error_message = generate_analysis(context_text)

    if payload is None:
        report.status = FinancialReportStatus.failed.value
        report.error_code = error_code
        report.error_message = error_message
        db.commit()

        emit_event(
            db,
            organization_id=report.organization_id,
            event_type=WebhookEventType.financial_insight_failed,
            object_type="financial_insight_report",
            object_id=report.id,
            payload={"report_id": report.id, "error_code": error_code},
            actor_user_id=report.created_by_user_id,
        )
        db.commit()
        return False

    report.status = FinancialReportStatus.completed.value
    report.ai_provider = provider_name
    report.ai_model = model_name
    report.structured_payload = payload.model_dump_json()
    report.generated_at = now
    report.expires_at = cache.compute_expires_at(now=now)
    report.error_code = None
    report.error_message = None
    db.commit()

    emit_event(
        db,
        organization_id=report.organization_id,
        event_type=WebhookEventType.financial_insight_generated,
        object_type="financial_insight_report",
        object_id=report.id,
        payload={"report_id": report.id},
        actor_user_id=report.created_by_user_id,
    )
    db.commit()
    return True
