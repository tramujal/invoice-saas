"""Phase 24.3 -- the AI Financial Advisor.

Covers: prompt building, strict schema validation (including rejection
and one retry on a malformed response), fingerprinting/report reuse,
request/generation flow, notification + audit fan-out via emit_event,
permission/tenant-isolation/plan-gating/quota enforcement at the HTTP
layer. No raw invoices, no PII, no fabricated numbers -- every value the
AI is shown comes from the existing deterministic Phase 24.1/24.2
builders, never recomputed here.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.ai.base import AIProviderError, ToolInvocation
from app.financial_intelligence import cache, insight_builder, prompt_builder, recommendations
from app.financial_report_status import FinancialReportStatus
from app.models import AuditEntry, FinancialInsightReport, Notification
from app.schemas import InvoiceLineItemCreate
from app.services.background_jobs import enqueue_job
from tests.factories import make_invoice, make_org_with_owner_on_plan


def _fi_org(db, **overrides):
    defaults = dict(
        advanced_financial_analytics_enabled=True,
        revenue_forecasting_enabled=True,
        ai_financial_recommendations_enabled=True,
        monthly_financial_ai_reports=10,
    )
    defaults.update(overrides)
    return make_org_with_owner_on_plan(db, **defaults)


def _valid_analysis_dict(**overrides) -> dict:
    base = {
        "executive_summary": "Revenue is stable with modest growth this month.",
        "overall_health": "good",
        "confidence_notice": "Based on limited history; confidence is currently low.",
        "observations": [
            {
                "category": "revenue",
                "severity": "info",
                "title": "Revenue grew slightly",
                "explanation": "Invoiced revenue increased compared to the prior month.",
                "evidence": [{"label": "Revenue this month", "value": "USD 1200.00"}],
            }
        ],
        "recommendations": [],
        "forecast_commentary": "Not enough history yet for a reliable forecast.",
        "strengths": [],
        "risks": [],
        "opportunities": [],
        "next_actions": [],
        "disclaimer": "This analysis is generated from deterministic metrics and is not financial, tax, or legal advice.",
    }
    base.update(overrides)
    return base


def _tool_call(arguments: dict) -> ToolInvocation:
    return ToolInvocation(name=prompt_builder.TOOL_NAME, arguments=arguments)


# --- Prompt builder / structured context ------------------------------------


def test_render_context_text_includes_metrics_header_and_is_bounded(db_session):
    org = _fi_org(db_session)
    context = insight_builder.build_structured_context(db_session, org.organization.id)
    text = prompt_builder.render_context_text(context)
    assert text.startswith("METRICS:\n")
    assert len(text) <= prompt_builder.FINANCIAL_AI_MAX_CONTEXT_CHARS + len("METRICS:\n... (truncated)")


def test_structured_context_never_includes_customer_pii(db_session):
    org = _fi_org(db_session)
    make_invoice(
        db_session,
        org.organization,
        org.user,
        line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=Decimal("100"))],
    )
    context = insight_builder.build_structured_context(db_session, org.organization.id)
    text = prompt_builder.render_context_text(context)
    assert "@example.com" not in text  # no email address ever appears
    assert "customer@example.com" not in text


# --- Fingerprint / reuse ------------------------------------------------


def test_fingerprint_stable_for_identical_data_and_changes_when_data_changes(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    context_a = insight_builder.build_structured_context(db_session, org.organization.id, now=now)
    context_b = insight_builder.build_structured_context(db_session, org.organization.id, now=now)
    assert cache.compute_source_fingerprint(context_a) == cache.compute_source_fingerprint(context_b)

    make_invoice(
        db_session,
        org.organization,
        org.user,
        line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=Decimal("500"))],
    )
    context_c = insight_builder.build_structured_context(db_session, org.organization.id, now=now)
    assert cache.compute_source_fingerprint(context_a) != cache.compute_source_fingerprint(context_c)


def test_fingerprint_ignores_generated_at_timestamp(db_session):
    org = _fi_org(db_session)
    context_a = insight_builder.build_structured_context(
        db_session, org.organization.id, now=datetime(2026, 3, 15, tzinfo=timezone.utc)
    )
    context_b = insight_builder.build_structured_context(
        db_session, org.organization.id, now=datetime(2026, 3, 15, 23, 59, tzinfo=timezone.utc)
    )
    assert cache.compute_source_fingerprint(context_a) == cache.compute_source_fingerprint(context_b)


def test_find_reusable_report_respects_expiry(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    report = FinancialInsightReport(
        organization_id=org.organization.id,
        status=FinancialReportStatus.completed.value,
        period_start=now.date(),
        period_end=now.date(),
        source_fingerprint="abc123",
        generated_at=now,
        expires_at=now,  # already at the boundary -> expired
    )
    db_session.add(report)
    db_session.commit()

    assert cache.find_reusable_report(db_session, org.organization.id, "abc123", now=now) is None

    report.expires_at = datetime(2026, 3, 16, tzinfo=timezone.utc)
    db_session.commit()
    reusable = cache.find_reusable_report(db_session, org.organization.id, "abc123", now=now)
    assert reusable is not None
    assert reusable.id == report.id


# --- generate_analysis: validation + retry ----------------------------------


def test_generate_analysis_returns_validated_payload_on_success(fake_ai_provider):
    fake_ai_provider.events = [_tool_call(_valid_analysis_dict())]
    payload, provider_name, model_name, error_code, error_message = recommendations.generate_analysis("METRICS:\n{}")
    assert payload is not None
    assert payload.overall_health == "good"
    assert error_code is None
    assert len(fake_ai_provider.calls) == 1


def test_generate_analysis_rejects_response_with_no_tool_call_and_retries_once(fake_ai_provider):
    fake_ai_provider.events = []  # model never calls the tool
    payload, _provider, _model, error_code, error_message = recommendations.generate_analysis("METRICS:\n{}")
    assert payload is None
    assert error_code == "invalid_response"
    assert len(fake_ai_provider.calls) == 2  # one real attempt + one retry


def test_generate_analysis_rejects_malformed_schema(fake_ai_provider):
    malformed = _valid_analysis_dict(observations=[])  # violates min_length=1 on observations
    fake_ai_provider.events = [_tool_call(malformed)]
    payload, _provider, _model, error_code, _msg = recommendations.generate_analysis("METRICS:\n{}")
    assert payload is None
    assert error_code == "invalid_response"


def test_generate_analysis_succeeds_on_retry_after_first_failure(monkeypatch):
    """A stateful fake distinct from the shared fixture -- the shared
    FakeAIProvider always yields the same scripted events, but this test
    specifically needs attempt 1 to fail and attempt 2 to succeed."""

    class FlakyProvider:
        def __init__(self):
            self.call_count = 0

        def stream_complete(self, system, messages, tools=()):
            self.call_count += 1
            if self.call_count == 1:
                return iter([])  # no tool call -> triggers a retry
            return iter([_tool_call(_valid_analysis_dict())])

    flaky = FlakyProvider()
    monkeypatch.setattr("app.financial_intelligence.recommendations.get_ai_provider", lambda *a, **kw: flaky)

    payload, _provider, _model, error_code, _msg = recommendations.generate_analysis("METRICS:\n{}")
    assert payload is not None
    assert error_code is None
    assert flaky.call_count == 2


def test_generate_analysis_records_provider_error(fake_ai_provider):
    from tests.fakes import make_ai_error

    fake_ai_provider.error = make_ai_error()
    payload, _provider, _model, error_code, _msg = recommendations.generate_analysis("METRICS:\n{}")
    assert payload is None
    assert error_code == "provider_error"


# --- request_insight_report / run_generation (service-level flow) ----------


def test_request_insight_report_creates_pending_row_and_enqueues_job(db_session):
    org = _fi_org(db_session)
    report, reused = recommendations.request_insight_report(
        db_session, org.organization.id, requested_by_user_id=org.user.id
    )
    assert reused is False
    assert report.status == FinancialReportStatus.pending.value
    assert report.created_by_user_id == org.user.id

    requested_entries = (
        db_session.query(AuditEntry)
        .filter(AuditEntry.event_type == "financial_insight.requested")
        .all()
    )
    assert len(requested_entries) == 1
    assert requested_entries[0].resource_id == report.id


def test_request_insight_report_reuses_existing_completed_report_when_not_forced(db_session, fake_ai_provider):
    org = _fi_org(db_session)
    fake_ai_provider.events = [_tool_call(_valid_analysis_dict())]

    first, reused_first = recommendations.request_insight_report(
        db_session, org.organization.id, requested_by_user_id=org.user.id
    )
    assert reused_first is False
    assert recommendations.run_generation(db_session, first.id) is True

    second, reused_second = recommendations.request_insight_report(
        db_session, org.organization.id, requested_by_user_id=org.user.id
    )
    assert reused_second is True
    assert second.id == first.id  # same row, no new report created


def test_request_insight_report_force_always_creates_new_row(db_session, fake_ai_provider):
    org = _fi_org(db_session)
    fake_ai_provider.events = [_tool_call(_valid_analysis_dict())]

    first, _ = recommendations.request_insight_report(
        db_session, org.organization.id, requested_by_user_id=org.user.id
    )
    recommendations.run_generation(db_session, first.id)

    second, reused = recommendations.request_insight_report(
        db_session, org.organization.id, requested_by_user_id=org.user.id, force=True
    )
    assert reused is False
    assert second.id != first.id


def test_run_generation_completes_report_and_notifies_and_audits(db_session, fake_ai_provider):
    org = _fi_org(db_session)
    fake_ai_provider.events = [_tool_call(_valid_analysis_dict())]

    report, _reused = recommendations.request_insight_report(
        db_session, org.organization.id, requested_by_user_id=org.user.id
    )
    succeeded = recommendations.run_generation(db_session, report.id)
    assert succeeded is True

    db_session.refresh(report)
    assert report.status == FinancialReportStatus.completed.value
    assert report.ai_provider == "fakeai"  # type(FakeAIProvider).__name__ minus "Provider", lowercased
    assert report.structured_payload is not None
    assert report.expires_at is not None

    generated_entries = (
        db_session.query(AuditEntry).filter(AuditEntry.event_type == "financial_insight.generated").all()
    )
    assert len(generated_entries) == 1

    notifications = (
        db_session.query(Notification).filter(Notification.event_type == "financial_insight.generated").all()
    )
    assert len(notifications) >= 1
    assert notifications[0].title == "Financial analysis ready"


def test_run_generation_records_failure_without_crashing(db_session, fake_ai_provider):
    from tests.fakes import make_ai_error

    org = _fi_org(db_session)
    fake_ai_provider.error = make_ai_error()

    report, _reused = recommendations.request_insight_report(
        db_session, org.organization.id, requested_by_user_id=org.user.id
    )
    succeeded = recommendations.run_generation(db_session, report.id)
    assert succeeded is False

    db_session.refresh(report)
    assert report.status == FinancialReportStatus.failed.value
    assert report.error_code == "provider_error"
    assert report.structured_payload is None

    failed_entries = (
        db_session.query(AuditEntry).filter(AuditEntry.event_type == "financial_insight.failed").all()
    )
    assert len(failed_entries) == 1


def test_background_job_is_enqueued_and_executable(db_session, fake_ai_provider):
    """Exercises the real job queue (enqueue + claim + run), not just a
    direct call to run_generation, to prove the handler wiring itself
    (app.jobs.handlers.financial_intelligence) is correct end to end."""
    from app.services.background_jobs import claim_jobs, run_claimed_job

    org = _fi_org(db_session)
    fake_ai_provider.events = [_tool_call(_valid_analysis_dict())]

    report, _reused = recommendations.request_insight_report(
        db_session, org.organization.id, requested_by_user_id=org.user.id
    )
    claimed = claim_jobs(db_session, worker_id="test-worker", queue="default", batch_size=5)
    job = next(j for j in claimed if j.job_type == "financial_insight.generate")
    result = run_claimed_job(db_session, job)
    assert result.outcome.value == "succeeded"

    db_session.refresh(report)
    assert report.status == FinancialReportStatus.completed.value


# --- HTTP layer: permissions, tenant isolation, plan gating, quota ---------


def test_insights_endpoints_require_authentication(client, db_session):
    org = _fi_org(db_session, email="ai-auth@example.com")
    response = client.get(f"/organizations/{org.organization.id}/financial-intelligence/insights/latest")
    assert response.status_code == 401


def test_insights_endpoints_reject_foreign_user(client, db_session):
    org_a = _fi_org(db_session, email="ai-tenant-a@example.com")
    org_b = _fi_org(db_session, email="ai-tenant-b@example.com")
    response = client.get(
        f"/organizations/{org_a.organization.id}/financial-intelligence/insights/latest",
        headers=org_b.auth_headers,
    )
    assert response.status_code == 403


def test_latest_insight_is_null_when_none_generated_yet(client, db_session):
    org = _fi_org(db_session, email="ai-empty@example.com")
    response = client.get(
        f"/organizations/{org.organization.id}/financial-intelligence/insights/latest",
        headers=org.auth_headers,
    )
    assert response.status_code == 200
    assert response.json() is None


def test_generate_denies_without_ai_capability(client, db_session):
    org = _fi_org(db_session, ai_financial_recommendations_enabled=False, email="ai-noplan@example.com")
    response = client.post(
        f"/organizations/{org.organization.id}/financial-intelligence/insights/generate",
        json={},
        headers=org.auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "ai_financial_recommendations"


def test_generate_respects_monthly_quota(client, db_session, fake_ai_provider):
    org = _fi_org(db_session, monthly_financial_ai_reports=1, email="ai-quota@example.com")
    fake_ai_provider.events = [_tool_call(_valid_analysis_dict())]

    first = client.post(
        f"/organizations/{org.organization.id}/financial-intelligence/insights/generate",
        json={"force": True},
        headers=org.auth_headers,
    )
    assert first.status_code == 200

    second = client.post(
        f"/organizations/{org.organization.id}/financial-intelligence/insights/generate",
        json={"force": True},
        headers=org.auth_headers,
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "plan_limit_reached"
    assert second.json()["detail"]["resource"] == "financial_ai_reports"


def test_generate_then_latest_reflects_completed_analysis(client, db_session, fake_ai_provider):
    org = _fi_org(db_session, email="ai-flow@example.com")
    fake_ai_provider.events = [_tool_call(_valid_analysis_dict())]

    generate_response = client.post(
        f"/organizations/{org.organization.id}/financial-intelligence/insights/generate",
        json={},
        headers=org.auth_headers,
    )
    assert generate_response.status_code == 200
    report_id = generate_response.json()["id"]
    assert generate_response.json()["status"] == "pending"

    # Synchronously run the enqueued job (mirrors the worker's real
    # execution, without spinning up the whole polling loop).
    assert recommendations.run_generation(db_session, report_id) is True

    latest_response = client.get(
        f"/organizations/{org.organization.id}/financial-intelligence/insights/latest",
        headers=org.auth_headers,
    )
    assert latest_response.status_code == 200
    body = latest_response.json()
    assert body["status"] == "completed"
    assert body["analysis"]["overall_health"] == "good"
    assert body["analysis"]["observations"][0]["evidence"][0]["label"] == "Revenue this month"


def test_tenant_isolation_reports_never_cross_organizations(db_session, fake_ai_provider):
    org_a = _fi_org(db_session, email="ai-iso-a@example.com")
    org_b = _fi_org(db_session, email="ai-iso-b@example.com")
    fake_ai_provider.events = [_tool_call(_valid_analysis_dict())]

    report_a, _ = recommendations.request_insight_report(
        db_session, org_a.organization.id, requested_by_user_id=org_a.user.id
    )
    recommendations.run_generation(db_session, report_a.id)

    latest_b = cache.get_latest_report(db_session, org_b.organization.id)
    assert latest_b is None
