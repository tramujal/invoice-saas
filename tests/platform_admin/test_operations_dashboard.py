"""Phase 21 -- Platform Operations Dashboard.

Covers: app.platform_metrics.business/usage/growth/health's own query
math (MRR/ARR/churn/conversion, usage counts, growth buckets, extended
system health), the three new GET /admin/dashboard/{business,usage,growth}
endpoints and the extended GET /admin/system/health endpoint (shape,
permission gating), and app.request_metrics's middleware-fed snapshot.
Zero regressions on the existing /admin/dashboard endpoint (see
test_dashboard.py, untouched by this phase).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.billing_period import BillingPeriod
from app.models import SubscriptionEvent
from app.platform_metrics.business import compute_business_metrics
from app.platform_metrics.growth import compute_growth_metrics
from app.platform_metrics.health import database_size_mb, queue_status, storage_used_mb
from app.platform_metrics.usage import compute_usage_metrics
from app.request_metrics import get_snapshot, record_request
from app.subscription_event_type import SubscriptionEventType
from app.subscription_status import SubscriptionStatus

from tests.factories import make_org_with_owner, make_plan, make_subscription, make_user


class TestBusinessMetrics:
    def test_mrr_sums_active_paying_subscriptions_normalized_to_monthly(self, db_session):
        paid_plan = make_plan(
            db_session, code="paid-monthly", monthly_price=Decimal("29.00"), yearly_price=Decimal("290.00")
        )
        owner = make_org_with_owner(db_session, email="paying@example.com")
        make_subscription(db_session, owner.organization, plan=paid_plan, status=SubscriptionStatus.active)

        metrics = compute_business_metrics(db_session)

        assert metrics.mrr >= Decimal("29.00")
        assert metrics.arr == metrics.mrr * 12
        assert metrics.paying_organizations >= 1

    def test_yearly_billing_period_is_normalized_by_dividing_by_12(self, db_session):
        paid_plan = make_plan(db_session, code="paid-yearly", monthly_price=Decimal("100.00"), yearly_price=Decimal("120.00"))
        owner = make_org_with_owner(db_session, email="yearly@example.com")
        make_subscription(
            db_session,
            owner.organization,
            plan=paid_plan,
            status=SubscriptionStatus.active,
            billing_period=BillingPeriod.yearly,
        )

        metrics = compute_business_metrics(db_session)

        # 120/12 = 10, not the 100 monthly_price -- proves the yearly
        # price is what's actually used for a yearly subscription.
        assert metrics.mrr == Decimal("10.00")

    def test_free_plan_subscriptions_are_not_counted_as_paying(self, db_session):
        make_org_with_owner(db_session, email="free@example.com")

        metrics = compute_business_metrics(db_session)

        assert metrics.paying_organizations == 0
        assert metrics.mrr == Decimal("0")

    def test_custom_pricing_null_plan_is_excluded_from_mrr_but_still_counts_as_paying(self, db_session):
        enterprise_plan = make_plan(db_session, code="custom-enterprise", monthly_price=None, yearly_price=None)
        owner = make_org_with_owner(db_session, email="enterprise@example.com")
        make_subscription(db_session, owner.organization, plan=enterprise_plan, status=SubscriptionStatus.active)

        metrics = compute_business_metrics(db_session)

        assert metrics.paying_organizations == 1
        assert metrics.mrr == Decimal("0")  # nothing honest to add

    def test_trialing_subscriptions_count_as_trial_not_paying(self, db_session):
        paid_plan = make_plan(db_session, code="trial-plan", monthly_price=Decimal("19.00"))
        owner = make_org_with_owner(db_session, email="trialing@example.com")
        make_subscription(db_session, owner.organization, plan=paid_plan, status=SubscriptionStatus.trialing)

        metrics = compute_business_metrics(db_session)

        assert metrics.trial_organizations >= 1
        assert metrics.mrr == Decimal("0")

    def test_active_users_counts_distinct_users_with_an_active_membership(self, db_session):
        make_org_with_owner(db_session, email="active-user@example.com")

        metrics = compute_business_metrics(db_session)

        assert metrics.active_users_total >= 1

    def test_churn_rate_reflects_canceled_events_in_window(self, db_session):
        paid_plan = make_plan(db_session, code="churn-plan", monthly_price=Decimal("50.00"))
        owner = make_org_with_owner(db_session, email="churned@example.com")
        subscription = make_subscription(db_session, owner.organization, plan=paid_plan, status=SubscriptionStatus.canceled)
        db_session.add(
            SubscriptionEvent(
                organization_id=owner.organization.id,
                subscription_id=subscription.id,
                event_type=SubscriptionEventType.subscription_canceled.value,
                created_at=datetime.now(timezone.utc) - timedelta(days=5),
            )
        )
        db_session.commit()

        metrics = compute_business_metrics(db_session)

        assert metrics.churn_rate_30d > 0

    def test_conversion_rate_reflects_trial_started_and_activated_events(self, db_session):
        paid_plan = make_plan(db_session, code="conversion-plan", monthly_price=Decimal("15.00"))
        owner = make_org_with_owner(db_session, email="converted@example.com")
        subscription = make_subscription(db_session, owner.organization, plan=paid_plan, status=SubscriptionStatus.active)
        now = datetime.now(timezone.utc) - timedelta(days=5)
        db_session.add_all(
            [
                SubscriptionEvent(
                    organization_id=owner.organization.id,
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.trial_started.value,
                    created_at=now,
                ),
                SubscriptionEvent(
                    organization_id=owner.organization.id,
                    subscription_id=subscription.id,
                    event_type=SubscriptionEventType.subscription_activated.value,
                    created_at=now,
                ),
            ]
        )
        db_session.commit()

        metrics = compute_business_metrics(db_session)

        assert metrics.conversion_rate_30d == 100.0

    def test_average_revenue_per_organization_is_mrr_over_paying_count(self, db_session):
        paid_plan = make_plan(db_session, code="arpu-plan", monthly_price=Decimal("40.00"))
        owner1 = make_org_with_owner(db_session, email="arpu1@example.com")
        owner2 = make_org_with_owner(db_session, email="arpu2@example.com", org_name="ARPU Co 2")
        make_subscription(db_session, owner1.organization, plan=paid_plan, status=SubscriptionStatus.active)
        make_subscription(db_session, owner2.organization, plan=paid_plan, status=SubscriptionStatus.active)

        metrics = compute_business_metrics(db_session)

        assert metrics.average_revenue_per_organization == metrics.mrr / metrics.paying_organizations


class TestUsageMetrics:
    def test_returns_non_negative_counts_for_every_field(self, db_session):
        metrics = compute_usage_metrics(db_session)

        assert metrics.ai_requests_30d >= 0
        assert metrics.api_keys_active >= 0
        assert metrics.webhook_deliveries_30d >= 0
        assert metrics.background_jobs_30d >= 0
        assert metrics.emails_sent_30d >= 0
        assert metrics.notifications_created_30d >= 0


class TestGrowthMetrics:
    def test_daily_signups_reflects_a_freshly_created_organization(self, db_session):
        make_org_with_owner(db_session, email="signup-today@example.com")

        metrics = compute_growth_metrics(db_session, days=30)

        total_signups = sum(item.count for item in metrics.daily_signups)
        assert total_signups >= 1

    def test_feature_adoption_reflects_plan_flags_of_paying_subscriptions(self, db_session):
        ai_plan = make_plan(db_session, code="ai-feature-plan", monthly_price=Decimal("25.00"), ai_enabled=True)
        owner = make_org_with_owner(db_session, email="ai-adopter@example.com")
        make_subscription(db_session, owner.organization, plan=ai_plan, status=SubscriptionStatus.active)

        metrics = compute_growth_metrics(db_session, days=30)

        ai_row = next(row for row in metrics.feature_adoption if row.feature == "ai_enabled")
        assert ai_row.adopted_paying_organizations >= 1

    def test_monthly_growth_percent_is_a_float(self, db_session):
        metrics = compute_growth_metrics(db_session, days=30)
        assert isinstance(metrics.monthly_growth_percent, float)


class TestSystemHealthExtensions:
    def test_queue_status_reflects_job_statuses(self, db_session):
        status = queue_status(db_session)
        assert status.pending >= 0
        assert status.running >= 0
        assert status.failed_total >= 0

    def test_storage_used_mb_is_honestly_zero(self, db_session):
        assert storage_used_mb() == 0

    def test_database_size_mb_returns_a_number_on_sqlite(self, db_session):
        size = database_size_mb(db_session)
        assert size is not None
        assert size >= 0


class TestRequestMetrics:
    def test_snapshot_reflects_recorded_samples(self):
        record_request(duration_ms=12.5, is_error=False)
        record_request(duration_ms=50.0, is_error=True)

        snapshot = get_snapshot()

        assert snapshot.sample_count >= 2
        assert snapshot.average_latency_ms is not None
        assert snapshot.error_rate_percent is not None


class TestOperationsDashboardEndpoints:
    def test_business_endpoint_returns_expected_shape(self, client, db_session, super_admin_headers):
        response = client.get("/admin/dashboard/business", headers=super_admin_headers)

        assert response.status_code == 200
        body = response.json()
        for field in (
            "organizations_total",
            "active_users_total",
            "paying_organizations",
            "trial_organizations",
            "mrr",
            "arr",
            "currency",
            "churn_rate_30d",
            "conversion_rate_30d",
            "average_revenue_per_organization",
        ):
            assert field in body

    def test_usage_endpoint_returns_expected_shape(self, client, db_session, super_admin_headers):
        response = client.get("/admin/dashboard/usage", headers=super_admin_headers)

        assert response.status_code == 200
        body = response.json()
        for field in (
            "ai_requests_30d",
            "api_keys_active",
            "api_keys_used_7d",
            "webhook_deliveries_30d",
            "background_jobs_30d",
            "emails_sent_30d",
            "notifications_created_30d",
        ):
            assert field in body

    def test_growth_endpoint_returns_expected_shape(self, client, db_session, super_admin_headers):
        response = client.get("/admin/dashboard/growth", headers=super_admin_headers)

        assert response.status_code == 200
        body = response.json()
        assert "daily_signups" in body
        assert "weekly_active_organizations" in body
        assert "monthly_growth_percent" in body
        assert "feature_adoption" in body

    def test_growth_endpoint_accepts_days_query_param(self, client, db_session, super_admin_headers):
        response = client.get("/admin/dashboard/growth?days=7", headers=super_admin_headers)
        assert response.status_code == 200

    def test_growth_endpoint_rejects_out_of_range_days(self, client, db_session, super_admin_headers):
        response = client.get("/admin/dashboard/growth?days=0", headers=super_admin_headers)
        assert response.status_code == 422

    def test_system_health_endpoint_includes_phase_21_fields(self, client, db_session, super_admin_headers):
        response = client.get("/admin/system/health", headers=super_admin_headers)

        assert response.status_code == 200
        body = response.json()
        for field in (
            "queue_pending",
            "queue_running",
            "queue_retry_scheduled",
            "jobs_failed_total",
            "storage_used_mb",
            "database_size_mb",
            "average_api_latency_ms",
            "error_rate_percent",
            "request_sample_count",
        ):
            assert field in body

    def test_all_new_endpoints_require_dashboard_view_permission(self, client, db_session):
        from app.security import create_access_token

        user = make_user(db_session, email="not-admin-ops@example.com")
        headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

        for path in ("/admin/dashboard/business", "/admin/dashboard/usage", "/admin/dashboard/growth"):
            response = client.get(path, headers=headers)
            assert response.status_code == 403, path

    def test_existing_dashboard_endpoint_is_unaffected(self, client, db_session, super_admin_headers):
        """Regression guard -- Phase 21 must not have changed
        /admin/dashboard's own existing response shape."""
        response = client.get("/admin/dashboard", headers=super_admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert "organizations_total" in body
        assert "health" in body
        assert "queue_pending" in body["health"]
