from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.analytics.calculators.trends import (
    SeriesGranularity,
    get_customer_count_series,
    get_customer_growth_trend,
    get_invoice_count_series,
    get_invoice_count_trend,
    get_quote_conversion_series,
    get_quote_count_trend,
    get_revenue_series,
    get_revenue_trend,
)
from app.analytics.time_windows import TimeWindowKind, resolve_time_window
from app.analytics.trend_direction import TrendDirection
from app.models import Invoice
from app.schemas import CurrencyCode
from tests.factories import make_customer, make_invoice, make_org_with_owner, make_quote


def _windows(now=None):
    now = now or datetime.now(timezone.utc)
    current = resolve_time_window(TimeWindowKind.current_month, now=now)
    previous = resolve_time_window(TimeWindowKind.previous_month, now=now)
    return current, previous


class TestGetRevenueTrend:
    def test_empty_dataset_returns_empty_dict(self, db_session):
        org = make_org_with_owner(db_session, email="rt-empty@example.com")
        current, previous = _windows()
        assert get_revenue_trend(db_session, org.organization.id, current=current, previous=previous) == {}

    def test_growth_between_two_months(self, db_session):
        # A fixed reference instant, never datetime.now(): calendar months
        # vary from 28 to 31 days, so a hardcoded day-count offset (e.g.
        # "45 days ago") lands in the previous calendar month on some
        # real-world dates and two months back on others -- exactly what
        # made this test date-dependent (it failed in practice on dates
        # where the two preceding months summed to fewer than 45 days).
        # Pinning `now` removes that dependency; the window boundaries
        # are still resolved by the real resolve_time_window() production
        # code, and the fixture timestamps are placed unambiguously
        # inside those resolved boundaries rather than guessed at via a
        # day-count offset.
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        org = make_org_with_owner(db_session, email="rt-growth@example.com")
        current, previous = _windows(now)

        old = make_invoice(db_session, org.organization, org.user)
        old.created_at = previous.start + timedelta(days=1)
        db_session.commit()
        new_1 = make_invoice(db_session, org.organization, org.user)
        new_2 = make_invoice(db_session, org.organization, org.user)
        for inv in (new_1, new_2):
            inv.created_at = current.start + timedelta(days=1)
        db_session.commit()

        result = get_revenue_trend(db_session, org.organization.id, current=current, previous=previous)
        usd = result["USD"]
        assert usd.current == Decimal("200.00")
        assert usd.previous == Decimal("100.00")
        assert usd.absolute_difference == Decimal("100.00")
        assert usd.direction == TrendDirection.up

    def test_multi_currency_never_combined(self, db_session):
        org = make_org_with_owner(db_session, email="rt-multi@example.com")
        now = datetime.now(timezone.utc)
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.USD)
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.EUR)

        current, previous = _windows(now)
        result = get_revenue_trend(db_session, org.organization.id, current=current, previous=previous)
        assert set(result.keys()) == {"USD", "EUR"}
        assert result["USD"].current == Decimal("100.00")
        assert result["EUR"].current == Decimal("100.00")

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="rt-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="rt-tenant-b@example.com")
        make_invoice(db_session, org_a.organization, org_a.user)
        make_invoice(db_session, org_b.organization, org_b.user)
        make_invoice(db_session, org_b.organization, org_b.user)

        current, previous = _windows()
        result_a = get_revenue_trend(db_session, org_a.organization.id, current=current, previous=previous)
        result_b = get_revenue_trend(db_session, org_b.organization.id, current=current, previous=previous)
        assert result_a["USD"].current == Decimal("100.00")
        assert result_b["USD"].current == Decimal("200.00")


class TestGetInvoiceCountTrend:
    def test_single_month_history_has_no_previous_baseline(self, db_session):
        org = make_org_with_owner(db_session, email="ict-single@example.com")
        make_invoice(db_session, org.organization, org.user)
        current, previous = _windows()
        result = get_invoice_count_trend(db_session, org.organization.id, current=current, previous=previous)
        assert result.current == Decimal("1")
        assert result.previous == Decimal("0")
        assert result.percentage_difference is None
        assert result.direction == TrendDirection.unknown

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="ict-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="ict-tenant-b@example.com")
        make_invoice(db_session, org_a.organization, org_a.user)
        make_invoice(db_session, org_b.organization, org_b.user)
        make_invoice(db_session, org_b.organization, org_b.user)

        current, previous = _windows()
        result_a = get_invoice_count_trend(db_session, org_a.organization.id, current=current, previous=previous)
        result_b = get_invoice_count_trend(db_session, org_b.organization.id, current=current, previous=previous)
        assert result_a.current == Decimal("1")
        assert result_b.current == Decimal("2")


class TestGetCustomerGrowthTrend:
    def test_counts_customers_created_in_each_window(self, db_session):
        # Fixed reference instant -- see test_growth_between_two_months's
        # identical rationale above for why a hardcoded day-count offset
        # (the previous "45 days ago") is date-dependent and a
        # window-derived timestamp isn't.
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        org = make_org_with_owner(db_session, email="cgt@example.com")
        current, previous = _windows(now)

        old_customer = make_customer(db_session, org.organization, email="old@example.com")
        old_customer.created_at = previous.start + timedelta(days=1)
        db_session.commit()
        new1 = make_customer(db_session, org.organization, email="new1@example.com")
        new2 = make_customer(db_session, org.organization, email="new2@example.com")
        for customer in (new1, new2):
            customer.created_at = current.start + timedelta(days=1)
        db_session.commit()

        result = get_customer_growth_trend(db_session, org.organization.id, current=current, previous=previous)
        assert result.current == Decimal("2")
        assert result.previous == Decimal("1")
        assert result.direction == TrendDirection.up

    def test_empty_dataset(self, db_session):
        org = make_org_with_owner(db_session, email="cgt-empty@example.com")
        current, previous = _windows()
        result = get_customer_growth_trend(db_session, org.organization.id, current=current, previous=previous)
        assert result.current == Decimal("0")
        assert result.previous == Decimal("0")
        assert result.direction == TrendDirection.unknown


class TestGetQuoteCountTrend:
    def test_counts_quotes_created_in_window(self, db_session):
        org = make_org_with_owner(db_session, email="qct@example.com")
        make_quote(db_session, org.organization, org.user)
        make_quote(db_session, org.organization, org.user)

        current, previous = _windows()
        result = get_quote_count_trend(db_session, org.organization.id, current=current, previous=previous)
        assert result.current == Decimal("2")
        assert result.previous == Decimal("0")

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="qct-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="qct-tenant-b@example.com")
        make_quote(db_session, org_a.organization, org_a.user)
        make_quote(db_session, org_b.organization, org_b.user)
        make_quote(db_session, org_b.organization, org_b.user)

        current, previous = _windows()
        result_a = get_quote_count_trend(db_session, org_a.organization.id, current=current, previous=previous)
        result_b = get_quote_count_trend(db_session, org_b.organization.id, current=current, previous=previous)
        assert result_a.current == Decimal("1")
        assert result_b.current == Decimal("2")


class TestGetRevenueSeries:
    def test_empty_dataset_zero_fills_nothing(self, db_session):
        org = make_org_with_owner(db_session, email="rs-empty@example.com")
        now = datetime.now(timezone.utc)
        starts = [now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]
        result = get_revenue_series(db_session, org.organization.id, starts, SeriesGranularity.monthly)
        assert result == []  # no currency ever seen -- nothing to zero-fill

    def test_zero_fills_across_months_for_a_seen_currency(self, db_session):
        org = make_org_with_owner(db_session, email="rs-fill@example.com")
        now = datetime.now(timezone.utc)
        make_invoice(db_session, org.organization, org.user)
        month_starts = [
            (now.replace(day=1) - timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        ]
        result = get_revenue_series(db_session, org.organization.id, month_starts, SeriesGranularity.monthly)
        assert len(result) == 2
        assert result[0].value == Decimal("0.00")
        assert result[1].value == Decimal("100.00")
        assert all(p.currency_code == "USD" for p in result)

    def test_quarterly_granularity_buckets_by_quarter(self, db_session):
        org = make_org_with_owner(db_session, email="rs-quarterly@example.com")
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)  # Q3
        invoice = make_invoice(db_session, org.organization, org.user)
        db_session.execute(
            Invoice.__table__.update().where(Invoice.id == invoice.id).values(created_at=now)
        )
        db_session.commit()
        quarter_starts = [datetime(2026, 7, 1, tzinfo=timezone.utc)]
        result = get_revenue_series(db_session, org.organization.id, quarter_starts, SeriesGranularity.quarterly)
        assert len(result) == 1
        assert result[0].period == "2026-Q3"
        assert result[0].value == Decimal("100.00")

    def test_yearly_granularity_buckets_by_year(self, db_session):
        org = make_org_with_owner(db_session, email="rs-yearly@example.com")
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        invoice = make_invoice(db_session, org.organization, org.user)
        db_session.execute(
            Invoice.__table__.update().where(Invoice.id == invoice.id).values(created_at=now)
        )
        db_session.commit()
        year_starts = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        result = get_revenue_series(db_session, org.organization.id, year_starts, SeriesGranularity.yearly)
        assert len(result) == 1
        assert result[0].period == "2026"
        assert result[0].value == Decimal("100.00")


class TestGetInvoiceCountSeries:
    def test_counts_per_month_currency_agnostic(self, db_session):
        org = make_org_with_owner(db_session, email="ics@example.com")
        now = datetime.now(timezone.utc)
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.USD)
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.EUR)
        month_starts = [now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]
        result = get_invoice_count_series(db_session, org.organization.id, month_starts, SeriesGranularity.monthly)
        assert len(result) == 1
        assert result[0].value == Decimal("2")
        assert result[0].currency_code is None


class TestGetCustomerCountSeries:
    def test_counts_new_customers_per_month(self, db_session):
        org = make_org_with_owner(db_session, email="ccs@example.com")
        now = datetime.now(timezone.utc)
        make_customer(db_session, org.organization, email="a@example.com")
        make_customer(db_session, org.organization, email="b@example.com")
        month_starts = [now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]
        result = get_customer_count_series(db_session, org.organization.id, month_starts, SeriesGranularity.monthly)
        assert len(result) == 1
        assert result[0].value == Decimal("2")


class TestGetQuoteConversionSeries:
    def test_zero_when_no_quotes_converted(self, db_session):
        org = make_org_with_owner(db_session, email="qcs@example.com")
        now = datetime.now(timezone.utc)
        make_quote(db_session, org.organization, org.user)
        month_starts = [now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]
        result = get_quote_conversion_series(db_session, org.organization.id, month_starts, SeriesGranularity.monthly)
        assert len(result) == 1
        assert result[0].value == Decimal("0")
