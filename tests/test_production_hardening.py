"""Phase 26 -- production-readiness hardening regressions.

Covers the two behavior changes this phase made that are security- or
availability-relevant and could silently regress: the interactive API
docs being closed by default in production, and the AI Financial
Advisor's generate endpoint being rate-limited independently of its plan
quota (the quota alone is checked only AFTER an expensive deterministic
context build -- see app.rate_limit.FINANCIAL_AI_GENERATE_RULES).
"""

import importlib

import pytest

from tests.factories import make_org_with_owner_on_plan


class TestApiDocsExposure:
    """app.main._api_docs_enabled -- the resolver is tested directly
    rather than by re-importing the whole FastAPI app per case, since
    docs_url/redoc_url/openapi_url are bound once at app construction."""

    @pytest.mark.parametrize(
        "environment,api_docs_enabled,expected",
        [
            # Default (unset) -- open in development, closed in production.
            ("development", None, True),
            ("production", None, False),
            # Explicit opt-in re-opens them in production (this app ships a
            # documented public /api/v1 surface an operator may want to publish).
            ("production", "true", True),
            ("production", "1", True),
            # Explicit opt-out closes them even in development.
            ("development", "false", False),
            ("development", "0", False),
            # An unrecognized value falls back to the environment default
            # rather than failing open.
            ("production", "maybe", False),
        ],
    )
    def test_docs_default_closed_in_production(self, monkeypatch, environment, api_docs_enabled, expected):
        monkeypatch.setenv("ENVIRONMENT", environment)
        if api_docs_enabled is None:
            monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
        else:
            monkeypatch.setenv("API_DOCS_ENABLED", api_docs_enabled)

        import app.main

        reloaded = importlib.reload(app.main)
        try:
            assert reloaded._api_docs_enabled() is expected
        finally:
            # Restore the module to the ambient test environment so no
            # later test observes a production-configured app object.
            monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
            monkeypatch.setenv("ENVIRONMENT", "development")
            importlib.reload(app.main)

    def test_docs_are_served_under_the_default_test_environment(self, client):
        # The ambient test environment is non-production, so the docs stay
        # reachable -- proving the gate defaults open for developers.
        assert client.get("/openapi.json").status_code == 200


class TestFinancialAiGenerateRateLimit:
    def test_generate_is_rate_limited_independently_of_plan_quota(self, client, db_session):
        """An organization with a LARGE remaining quota still gets 429ed
        after FINANCIAL_AI_GENERATE_RULES' hourly limit -- proving the
        limit is not merely the quota by another name."""
        from app.rate_limit import FINANCIAL_AI_GENERATE_RULES

        limit = FINANCIAL_AI_GENERATE_RULES[0].limit
        org = make_org_with_owner_on_plan(
            db_session,
            email="ratelimit-ai@example.com",
            advanced_financial_analytics_enabled=True,
            ai_financial_recommendations_enabled=True,
            monthly_financial_ai_reports=None,  # unlimited quota
        )
        url = f"/organizations/{org.organization.id}/financial-intelligence/insights/generate"

        statuses = [
            client.post(url, json={"force": True}, headers=org.auth_headers).status_code
            for _ in range(limit + 2)
        ]
        assert 429 in statuses, f"expected a 429 within {limit + 2} calls, got {statuses}"
        assert statuses[0] == 200, "the first call should still succeed normally"

    def test_rate_limit_is_scoped_per_user_not_globally(self, client, db_session):
        """One organization exhausting its bucket must never lock out a
        different organization -- the buckets are keyed by user identity."""
        from app.rate_limit import FINANCIAL_AI_GENERATE_RULES

        limit = FINANCIAL_AI_GENERATE_RULES[0].limit
        plan_kwargs = dict(
            advanced_financial_analytics_enabled=True,
            ai_financial_recommendations_enabled=True,
            monthly_financial_ai_reports=None,
        )
        noisy = make_org_with_owner_on_plan(db_session, email="noisy-ai@example.com", **plan_kwargs)
        quiet = make_org_with_owner_on_plan(db_session, email="quiet-ai@example.com", **plan_kwargs)

        noisy_url = f"/organizations/{noisy.organization.id}/financial-intelligence/insights/generate"
        for _ in range(limit + 2):
            client.post(noisy_url, json={"force": True}, headers=noisy.auth_headers)

        quiet_url = f"/organizations/{quiet.organization.id}/financial-intelligence/insights/generate"
        assert client.post(quiet_url, json={"force": True}, headers=quiet.auth_headers).status_code == 200
