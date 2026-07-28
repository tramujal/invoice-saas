"""app.analytics.service.AnalyticsService -- the facade every router/
insights engine/assistant context builder goes through. These tests
cover the facade's own responsibilities: correct delegation, and that
dashboard_summary()/dashboard_analytics() (the relocated
get_dashboard_summary/get_dashboard_analytics_data logic) still produce
the exact same shape and figures they always did -- see
tests/insights/ and the dashboard router's own pre-existing test
coverage for the exhaustive behavioral tests this doesn't repeat.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.analytics.service import AnalyticsService
from app.analytics.time_windows import TimeWindowKind, resolve_time_window
from tests.factories import make_customer, make_invoice, make_org_with_owner


class TestAnalyticsServiceKpiMethods:
    def test_revenue_by_currency_delegates_correctly(self, db_session):
        org = make_org_with_owner(db_session, email="svc-revenue@example.com")
        make_invoice(db_session, org.organization, org.user)
        service = AnalyticsService(db_session, org.organization.id)
        assert service.revenue_by_currency() == {"USD": Decimal("100.00")}

    def test_is_constructed_per_organization_and_never_crosses_tenants(self, db_session):
        org_a = make_org_with_owner(db_session, email="svc-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="svc-tenant-b@example.com")
        make_invoice(db_session, org_a.organization, org_a.user)
        make_invoice(db_session, org_b.organization, org_b.user)
        make_invoice(db_session, org_b.organization, org_b.user)

        service_a = AnalyticsService(db_session, org_a.organization.id)
        service_b = AnalyticsService(db_session, org_b.organization.id)
        assert service_a.invoice_counts().total == 1
        assert service_b.invoice_counts().total == 2


class TestDashboardSummary:
    def test_matches_expected_shape_for_empty_org(self, db_session):
        org = make_org_with_owner(db_session, email="svc-dash-empty@example.com")
        summary = AnalyticsService(db_session, org.organization.id).dashboard_summary()
        assert summary.total_invoices == 0
        assert summary.total_customers == 0
        assert summary.revenue_by_currency == []
        assert summary.recent_invoices == []

    def test_growth_percent_is_none_without_a_prior_month(self, db_session):
        org = make_org_with_owner(db_session, email="svc-dash-growth@example.com")
        make_invoice(db_session, org.organization, org.user)
        summary = AnalyticsService(db_session, org.organization.id).dashboard_summary()
        assert len(summary.revenue_by_currency) == 1
        assert summary.revenue_by_currency[0].revenue_growth_percent is None

    def test_recent_invoices_capped_and_most_recent_first(self, db_session):
        org = make_org_with_owner(db_session, email="svc-dash-recent@example.com")
        now = datetime.now(timezone.utc)
        for i in range(8):
            invoice = make_invoice(db_session, org.organization, org.user)
            invoice.created_at = now - timedelta(days=8 - i)
        db_session.commit()

        summary = AnalyticsService(db_session, org.organization.id).dashboard_summary()
        assert len(summary.recent_invoices) == 5
        # Most recently created (smallest days-ago offset) comes first.
        timestamps = [inv.created_at for inv in summary.recent_invoices]
        assert timestamps == sorted(timestamps, reverse=True)


class TestDashboardAnalytics:
    def test_matches_expected_shape_for_empty_org(self, db_session):
        org = make_org_with_owner(db_session, email="svc-analytics-empty@example.com")
        analytics = AnalyticsService(db_session, org.organization.id).dashboard_analytics()
        assert analytics.top_customers == []
        assert analytics.top_products_and_services == []
        assert len(analytics.monthly_summary) == 6  # MONTHLY_SUMMARY_MONTHS

    def test_top_customers_reflects_real_data(self, db_session):
        org = make_org_with_owner(db_session, email="svc-analytics-top@example.com")
        customer = make_customer(db_session, org.organization)
        make_invoice(db_session, org.organization, org.user, customer=customer)

        analytics = AnalyticsService(db_session, org.organization.id).dashboard_analytics()
        assert len(analytics.top_customers) == 1
        assert analytics.top_customers[0].customer_id == customer.id
