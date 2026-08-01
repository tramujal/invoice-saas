from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.analytics.calculators.revenue import (
    get_monthly_revenue_series,
    get_revenue_breakdown,
    get_revenue_by_currency,
    get_revenue_growth,
)
from app.analytics.time_windows import TimeWindowKind, resolve_time_window
from app.models import Invoice
from app.payment_status import PaymentStatus
from app.schemas import CurrencyCode
from tests.factories import make_invoice, make_org_with_owner


def _insert_invoices_directly(db_session, organization, count: int) -> None:
    """See tests/analytics/test_invoice_calculators.py's identical
    helper -- bypasses create_invoice_record's plan-limit enforcement,
    which is irrelevant to this test's purpose (SQL-side sum correctness
    at scale)."""
    for i in range(count):
        db_session.add(
            Invoice(
                organization_id=organization.id,
                invoice_number=i + 1,
                subtotal=Decimal("100.00"),
                tax_amount=Decimal("0.00"),
                total=Decimal("100.00"),
                currency_code="USD",
            )
        )
    db_session.commit()


class TestGetRevenueByCurrency:
    def test_empty_dataset(self, db_session):
        org = make_org_with_owner(db_session, email="rev-empty@example.com")
        assert get_revenue_by_currency(db_session, org.organization.id) == {}

    def test_single_invoice(self, db_session):
        org = make_org_with_owner(db_session, email="rev-single@example.com")
        make_invoice(db_session, org.organization, org.user)
        assert get_revenue_by_currency(db_session, org.organization.id) == {"USD": Decimal("100.00")}

    def test_multiple_currencies_kept_separate(self, db_session):
        org = make_org_with_owner(db_session, email="rev-multi@example.com")
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.USD)
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.UYU)
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.USD)

        result = get_revenue_by_currency(db_session, org.organization.id)
        assert result == {"USD": Decimal("200.00"), "UYU": Decimal("100.00")}

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="rev-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="rev-tenant-b@example.com")
        make_invoice(db_session, org_a.organization, org_a.user)
        make_invoice(db_session, org_b.organization, org_b.user)
        make_invoice(db_session, org_b.organization, org_b.user)

        assert get_revenue_by_currency(db_session, org_a.organization.id) == {"USD": Decimal("100.00")}
        assert get_revenue_by_currency(db_session, org_b.organization.id) == {"USD": Decimal("200.00")}

    def test_large_dataset_sums_correctly(self, db_session):
        org = make_org_with_owner(db_session, email="rev-large@example.com")
        _insert_invoices_directly(db_session, org.organization, 200)
        assert get_revenue_by_currency(db_session, org.organization.id) == {
            "USD": Decimal("20000.00")
        }

    def test_window_filters_by_created_at(self, db_session):
        org = make_org_with_owner(db_session, email="rev-window@example.com")
        old = make_invoice(db_session, org.organization, org.user)
        old.created_at = datetime.now(timezone.utc) - timedelta(days=400)
        db_session.commit()
        make_invoice(db_session, org.organization, org.user)

        window = resolve_time_window(TimeWindowKind.current_year)
        result = get_revenue_by_currency(db_session, org.organization.id, window=window)
        assert result == {"USD": Decimal("100.00")}


class TestGetRevenueBreakdown:
    def test_paid_plus_outstanding_equals_total(self, db_session):
        org = make_org_with_owner(db_session, email="breakdown@example.com")
        make_invoice(db_session, org.organization, org.user)
        paid = make_invoice(db_session, org.organization, org.user)
        paid.payment_status = PaymentStatus.paid.value
        db_session.commit()

        [breakdown] = get_revenue_breakdown(db_session, org.organization.id)
        assert breakdown.total == Decimal("200.00")
        assert breakdown.paid == Decimal("100.00")
        assert breakdown.outstanding == Decimal("100.00")
        assert breakdown.paid + breakdown.outstanding == breakdown.total

    def test_overdue_uses_effective_status(self, db_session):
        org = make_org_with_owner(db_session, email="breakdown-overdue@example.com")
        invoice = make_invoice(db_session, org.organization, org.user)
        invoice.due_date = (datetime.now(timezone.utc) - timedelta(days=5)).date()
        db_session.commit()

        [breakdown] = get_revenue_breakdown(db_session, org.organization.id)
        assert breakdown.overdue == Decimal("100.00")
        assert breakdown.outstanding == Decimal("100.00")

    def test_empty_dataset_returns_empty_list(self, db_session):
        org = make_org_with_owner(db_session, email="breakdown-empty@example.com")
        assert get_revenue_breakdown(db_session, org.organization.id) == []


class TestGetRevenueGrowth:
    def test_positive_growth_between_windows(self, db_session):
        # A fixed reference instant, never datetime.now(): calendar months
        # vary from 28 to 31 days, so a hardcoded day-count offset (e.g.
        # "45 days ago") lands in the previous calendar month on some
        # real-world dates and two months back on others (e.g. any date
        # in the first half of a month whose two preceding months include
        # a short February) -- which is exactly what made this test
        # date-dependent. Pinning `now` removes that dependency; the
        # window boundaries themselves are still resolved by the real
        # resolve_time_window() production code, never recomputed by hand
        # here, and the fixture timestamps are placed unambiguously
        # inside those resolved boundaries rather than guessed at via a
        # day-count offset.
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        org = make_org_with_owner(db_session, email="growth@example.com")
        this_month = resolve_time_window(TimeWindowKind.current_month, now=now)
        last_month = resolve_time_window(TimeWindowKind.previous_month, now=now)

        old = make_invoice(db_session, org.organization, org.user)
        old.created_at = last_month.start + timedelta(days=1)
        db_session.commit()
        new_1 = make_invoice(db_session, org.organization, org.user)
        new_2 = make_invoice(db_session, org.organization, org.user)
        for inv in (new_1, new_2):
            inv.created_at = this_month.start + timedelta(days=1)
        db_session.commit()

        growth = get_revenue_growth(db_session, org.organization.id, current=this_month, previous=last_month)
        assert growth["USD"] == Decimal("100.00")  # 200 vs 100 = +100%

    def test_no_prior_baseline_returns_none(self, db_session):
        org = make_org_with_owner(db_session, email="growth-none@example.com")
        make_invoice(db_session, org.organization, org.user)

        now = datetime.now(timezone.utc)
        this_month = resolve_time_window(TimeWindowKind.current_month, now=now)
        last_month = resolve_time_window(TimeWindowKind.previous_month, now=now)
        growth = get_revenue_growth(db_session, org.organization.id, current=this_month, previous=last_month)
        assert growth.get("USD") is None


class TestGetMonthlyRevenueSeries:
    def test_zero_fills_currencies_across_every_month(self, db_session):
        org = make_org_with_owner(db_session, email="series@example.com")
        make_invoice(db_session, org.organization, org.user)
        now = datetime.now(timezone.utc)
        month_starts = [now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]

        series = get_monthly_revenue_series(db_session, org.organization.id, month_starts)
        assert len(series) == 1
        month, currency_code, revenue = series[0]
        assert currency_code == "USD"
        assert revenue == Decimal("100.00")
