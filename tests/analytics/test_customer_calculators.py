from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.analytics.calculators.customers import (
    get_customer_growth,
    get_customer_retention,
    get_top_customers,
)
from app.analytics.time_windows import TimeWindowKind, resolve_time_window
from tests.factories import make_customer, make_invoice, make_org_with_owner


class TestGetCustomerGrowth:
    def test_empty_dataset(self, db_session):
        org = make_org_with_owner(db_session, email="growth-empty@example.com")
        window = resolve_time_window(TimeWindowKind.current_month)
        assert get_customer_growth(db_session, org.organization.id, window=window) == 0

    def test_counts_only_customers_created_within_window(self, db_session):
        org = make_org_with_owner(db_session, email="growth-window@example.com")
        old_customer = make_customer(db_session, org.organization, email="old@example.com")
        old_customer.created_at = datetime.now(timezone.utc) - timedelta(days=90)
        db_session.commit()
        make_customer(db_session, org.organization, email="new@example.com")

        window = resolve_time_window(TimeWindowKind.last_30_days)
        assert get_customer_growth(db_session, org.organization.id, window=window) == 1

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="growth-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="growth-tenant-b@example.com")
        make_customer(db_session, org_a.organization)
        make_customer(db_session, org_b.organization)
        make_customer(db_session, org_b.organization, email="second@example.com")

        window = resolve_time_window(TimeWindowKind.current_year)
        assert get_customer_growth(db_session, org_a.organization.id, window=window) == 1
        assert get_customer_growth(db_session, org_b.organization.id, window=window) == 2


class TestGetCustomerRetention:
    def test_empty_dataset(self, db_session):
        org = make_org_with_owner(db_session, email="retention-empty@example.com")
        result = get_customer_retention(db_session, org.organization.id)
        assert result.total_invoiced_customers == 0
        assert result.retention_rate_percent is None

    def test_single_invoice_customer_is_not_a_repeat(self, db_session):
        org = make_org_with_owner(db_session, email="retention-single@example.com")
        customer = make_customer(db_session, org.organization)
        make_invoice(db_session, org.organization, org.user, customer=customer)

        result = get_customer_retention(db_session, org.organization.id)
        assert result.total_invoiced_customers == 1
        assert result.repeat_customers == 0
        assert result.retention_rate_percent == 0.0

    def test_repeat_customer_counted_correctly(self, db_session):
        org = make_org_with_owner(db_session, email="retention-repeat@example.com")
        repeat_customer = make_customer(db_session, org.organization, email="repeat@example.com")
        one_time_customer = make_customer(db_session, org.organization, email="onetime@example.com")
        make_invoice(db_session, org.organization, org.user, customer=repeat_customer)
        make_invoice(db_session, org.organization, org.user, customer=repeat_customer)
        make_invoice(db_session, org.organization, org.user, customer=one_time_customer)

        result = get_customer_retention(db_session, org.organization.id)
        assert result.total_invoiced_customers == 2
        assert result.repeat_customers == 1
        assert result.retention_rate_percent == 50.0

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="retention-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="retention-tenant-b@example.com")
        customer_a = make_customer(db_session, org_a.organization)
        make_invoice(db_session, org_a.organization, org_a.user, customer=customer_a)

        result_b = get_customer_retention(db_session, org_b.organization.id)
        assert result_b.total_invoiced_customers == 0


class TestGetTopCustomers:
    def test_ranked_independently_per_currency(self, db_session):
        org = make_org_with_owner(db_session, email="top-cust@example.com")
        big_spender = make_customer(db_session, org.organization, email="big@example.com")
        small_spender = make_customer(db_session, org.organization, email="small@example.com")
        make_invoice(db_session, org.organization, org.user, customer=big_spender)
        make_invoice(db_session, org.organization, org.user, customer=big_spender)
        make_invoice(db_session, org.organization, org.user, customer=small_spender)

        top = get_top_customers(db_session, org.organization.id)
        assert len(top) == 2
        assert top[0].customer_id == big_spender.id
        assert top[0].revenue == Decimal("200.00")
        assert top[1].customer_id == small_spender.id

    def test_limit_is_respected(self, db_session):
        org = make_org_with_owner(db_session, email="top-cust-limit@example.com")
        for i in range(5):
            customer = make_customer(db_session, org.organization, email=f"cust{i}@example.com")
            make_invoice(db_session, org.organization, org.user, customer=customer)

        top = get_top_customers(db_session, org.organization.id, limit=3)
        assert len(top) == 3

    def test_empty_dataset(self, db_session):
        org = make_org_with_owner(db_session, email="top-cust-empty@example.com")
        assert get_top_customers(db_session, org.organization.id) == []
