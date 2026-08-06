"""The financial_insight.generate job handler -- registered into
app.jobs.registry at import time (see this package's own __init__.py).

Mirrors app.jobs.handlers.webhook's exact distinction: a job "succeeding"
(JobOutcome.succeeded, the only outcome this handler ever returns under
normal operation) means "this job ROW finished running without
crashing" -- it says nothing about whether the underlying AI generation
itself succeeded. That business-level outcome lives entirely on the
FinancialInsightReport row's own `status` (completed/failed), set by
app.financial_intelligence.recommendations.run_generation, never on the
BackgroundJob row. Only a genuine, unexpected exception (a DB error, a
programming bug) should ever propagate out of run_generation -- that is
what turns into a retryable job-execution failure, via
app.services.background_jobs.run_claimed_job's own catch-all.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.financial_intelligence.recommendations import run_generation
from app.job_type import JobType
from app.jobs.registry import JobDefinition, JobOutcome, JobResult, register_job
from app.models import BackgroundJob


class FinancialInsightGeneratePayload(BaseModel):
    report_id: str


def handle_financial_insight_generate(
    db: Session, job: BackgroundJob, payload: FinancialInsightGeneratePayload
) -> JobResult:
    succeeded = run_generation(db, payload.report_id)
    return JobResult(
        outcome=JobOutcome.succeeded,
        result_summary="report_completed" if succeeded else "report_failed",
    )


register_job(
    JobDefinition(
        job_type=JobType.financial_insight_generate,
        payload_schema=FinancialInsightGeneratePayload,
        handler=handle_financial_insight_generate,
        queue="default",
        priority=0,
        max_attempts=3,
        # An AI provider call can genuinely take longer than the default
        # 30s job timeout -- matches FINANCIAL_AI_TIMEOUT_SECONDS (45s)
        # plus headroom for the deterministic context-building queries.
        timeout_seconds=90,
        organization_id_required=True,
    )
)
