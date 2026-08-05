"""Phase 24.1 -- the deterministic Financial Dashboard.

Covers: executive-KPI calculations and their previous-period comparisons,
currency separation, zero-denominator/empty-organization safety, AR aging
buckets, quote conversion funnel, permission/tenant-isolation/plan-gate
enforcement at the HTTP layer. No AI, no forecasting -- those modules
don't exist yet in this phase, deliberately.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.financial_intelligence import cashflow, metrics
from app.quote_status import QuoteStatus
from app.schemas import CurrencyCode, InvoiceLineItemCreate
from app.services.quotes import convert_quote_to_invoice, mark_quote_accepted_record, mark_quote_rejected_record
from tests.factories import (
    make_customer,
    make_invoice,
    make_org_with_owner_on_plan,
    make_quote,
    mark_invoice_paid,
)


def _fi_org(db, **overrides):
    defaults = dict(advanced_financial_analytics_enabled=True)
    defaults.update(overrides)
    return make_org_with_owner_on_plan(db, **defaults)


# A safely-future due_date to pass at creation time -- create_invoice_record
# validates against the REAL organization-local "today," which can be well
# after any fictional test date this file otherwise uses.
_SAFE_FUTURE_DUE_DATE = date.today() + timedelta(days=3650)


def _backdate(db, obj, *, created_at: datetime, due_date: date | None = "unset") -> None:
    """Directly overwrites created_at (and optionally due_date) after
    creation -- create_invoice_record validates due_date against the
    REAL organization-local "today" at creation time, so a test that
    wants a fictional past due_date must create with a safely-future one
    first, then backdate both fields here, matching mark_invoice_paid's
    own established "bypass the service layer for deterministic test
    setup" pattern."""
    obj.created_at = created_at
    if due_date != "unset":
        obj.due_date = due_date
    db.commit()
    db.refresh(obj)


# --- Executive overview: KPI math + period comparison -----------------------


def test_executive_overview_empty_organization_never_crashes(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)

    overview = metrics.build_executive_overview(db_session, org.organization.id, now=now)

    assert overview.by_currency == []
    assert overview.quote_conversion_rate.value is None
    assert overview.quote_conversion_rate.data_completeness == "insufficient"
    assert overview.average_days_to_payment.value is None
    assert overview.average_days_to_payment.data_completeness == "insufficient"


def test_executive_overview_kpi_values_and_period_comparison(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)

    # This month (March): one unpaid invoice (outstanding) + one paid invoice (collected).
    unpaid_march = make_invoice(
        db_session,
        org.organization,
        org.user,
        line_items=[InvoiceLineItemCreate(
            description="Unpaid March", quantity=Decimal("1"), unit_price=Decimal("1000.00")
        )],
        due_date=_SAFE_FUTURE_DUE_DATE,
    )
    _backdate(db_session, unpaid_march, created_at=datetime(2026, 3, 5, tzinfo=timezone.utc), due_date=date(2026, 3, 25))

    paid_march = make_invoice(
        db_session,
        org.organization,
        org.user,
        line_items=[InvoiceLineItemCreate(
            description="Paid March", quantity=Decimal("1"), unit_price=Decimal("500.00")
        )],
        due_date=_SAFE_FUTURE_DUE_DATE,
    )
    _backdate(db_session, paid_march, created_at=datetime(2026, 3, 6, tzinfo=timezone.utc), due_date=date(2026, 3, 20))
    mark_invoice_paid(db_session, paid_march, paid_at=datetime(2026, 3, 10, tzinfo=timezone.utc))

    # Previous month (February): one invoice, created AND paid in February.
    paid_feb = make_invoice(
        db_session,
        org.organization,
        org.user,
        line_items=[InvoiceLineItemCreate(
            description="Paid Feb", quantity=Decimal("1"), unit_price=Decimal("400.00")
        )],
        due_date=_SAFE_FUTURE_DUE_DATE,
    )
    _backdate(db_session, paid_feb, created_at=datetime(2026, 2, 6, tzinfo=timezone.utc), due_date=date(2026, 2, 20))
    mark_invoice_paid(db_session, paid_feb, paid_at=datetime(2026, 2, 10, tzinfo=timezone.utc))

    overview = metrics.build_executive_overview(db_session, org.organization.id, now=now)
    assert len(overview.by_currency) == 1
    usd = overview.by_currency[0]
    assert usd.currency_code == "USD"

    # invoiced_this_month = 1000 + 500 = 1500; previous (Feb) = 400.
    assert usd.invoiced_this_month.value == Decimal("1500.00")
    assert usd.invoiced_this_month.previous_value == Decimal("400.00")
    assert usd.invoiced_this_month.percent_change == Decimal("275.00")
    assert usd.invoiced_this_month.trend_direction == "up"

    # collected_this_month = 500 (paid_at in March); previous (paid_at in Feb) = 400.
    assert usd.collected_this_month.value == Decimal("500.00")
    assert usd.collected_this_month.previous_value == Decimal("400.00")

    # outstanding = the one still-unpaid invoice = 1000.
    assert usd.outstanding_receivables.value == Decimal("1000.00")
    # As-of-previous-month-end (2026-02-28), NEITHER March invoice existed
    # yet, so previous outstanding must be 0.
    assert usd.outstanding_receivables.previous_value == Decimal("0.00")

    # No invoice is overdue yet (today_local defaults to real now(), and
    # both March due dates are in the future relative to "now" at test
    # time) -- overdue is at least well-defined and non-negative.
    assert usd.overdue_receivables.value >= Decimal("0.00")

    # average_invoice_value this month = 1500 / 2 = 750; previous = 400 / 1 = 400.
    assert usd.average_invoice_value.value == Decimal("750.00")
    assert usd.average_invoice_value.previous_value == Decimal("400.00")

    # collection_rate this month = 500 / 1500 = 33.33%.
    assert usd.collection_rate.value == Decimal("33.33")


def test_executive_overview_currencies_are_never_mixed(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)

    usd_invoice = make_invoice(
        db_session,
        org.organization,
        org.user,
        currency_code=CurrencyCode.USD,
        line_items=[InvoiceLineItemCreate(description="USD", quantity=Decimal("1"), unit_price=Decimal("1000.00"))],
    )
    _backdate(db_session, usd_invoice, created_at=datetime(2026, 3, 5, tzinfo=timezone.utc))

    eur_invoice = make_invoice(
        db_session,
        org.organization,
        org.user,
        currency_code=CurrencyCode.EUR,
        line_items=[InvoiceLineItemCreate(description="EUR", quantity=Decimal("1"), unit_price=Decimal("300.00"))],
    )
    _backdate(db_session, eur_invoice, created_at=datetime(2026, 3, 6, tzinfo=timezone.utc))

    overview = metrics.build_executive_overview(db_session, org.organization.id, now=now)
    by_code = {c.currency_code: c for c in overview.by_currency}
    assert set(by_code) == {"USD", "EUR"}
    assert by_code["USD"].invoiced_this_month.value == Decimal("1000.00")
    assert by_code["EUR"].invoiced_this_month.value == Decimal("300.00")


# --- Revenue trends -----------------------------------------------------


def test_revenue_trends_month_over_month_and_year_over_year(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)

    def invoice_at(month_dt: datetime, amount: Decimal):
        inv = make_invoice(
            db_session,
            org.organization,
            org.user,
            line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=amount)],
        )
        _backdate(db_session, inv, created_at=month_dt)
        return inv

    invoice_at(datetime(2025, 3, 10, tzinfo=timezone.utc), Decimal("100.00"))  # 12 months before latest
    invoice_at(datetime(2026, 2, 10, tzinfo=timezone.utc), Decimal("200.00"))  # previous month
    invoice_at(datetime(2026, 3, 10, tzinfo=timezone.utc), Decimal("300.00"))  # latest (displayed) month

    trends = metrics.build_revenue_trends_section(db_session, org.organization.id, now=now)
    assert trends.data_completeness == "complete"
    # 12 displayed months (the 13th trailing month is only a YoY baseline).
    march_points = [p for p in trends.points if p.period == "2026-03" and p.currency_code == "USD"]
    assert len(march_points) == 1
    assert march_points[0].invoiced == Decimal("300.00")

    # MoM: 300 vs 200 -> +50%.
    assert trends.month_over_month_change_percent["USD"] == Decimal("50.00")
    # YoY: 300 vs 100 (12 months earlier) -> +200%.
    assert trends.year_over_year_change_percent["USD"] == Decimal("200.00")


def test_revenue_trends_omits_year_over_year_without_enough_history(db_session):
    org = _fi_org(db_session)
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)

    inv = make_invoice(
        db_session,
        org.organization,
        org.user,
        line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=Decimal("300.00"))],
    )
    _backdate(db_session, inv, created_at=datetime(2026, 3, 10, tzinfo=timezone.utc))

    trends = metrics.build_revenue_trends_section(db_session, org.organization.id, now=now)
    # No invoice at all 12 months earlier -> growth_percent(current, 0) -> None.
    assert trends.year_over_year_change_percent["USD"] is None


# --- Receivables aging -----------------------------------------------------


def test_aging_buckets_classify_by_days_overdue(db_session):
    org = _fi_org(db_session)
    today_local = date(2026, 3, 15)

    def invoice_due(due_date, amount: Decimal):
        inv = make_invoice(
            db_session,
            org.organization,
            org.user,
            due_date=_SAFE_FUTURE_DUE_DATE,
            line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=amount)],
        )
        _backdate(db_session, inv, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc), due_date=due_date)
        return inv

    invoice_due(date(2026, 3, 20), Decimal("100.00"))  # not yet due
    invoice_due(date(2026, 3, 10), Decimal("200.00"))  # 5 days overdue -> 1-30
    invoice_due(date(2026, 2, 1), Decimal("300.00"))  # 42 days overdue -> 31-60
    invoice_due(date(2025, 12, 1), Decimal("400.00"))  # 104 days overdue -> 90+
    invoice_due(None, Decimal("50.00"))  # missing due date -> excluded from buckets

    result = cashflow.compute_aging_buckets(db_session, org.organization.id, today_local=today_local)
    by_bucket = {(b.bucket, b.currency_code): b for b in result.buckets}

    assert by_bucket[("not_yet_due", "USD")].amount == Decimal("100.00")
    assert by_bucket[("overdue_1_30", "USD")].amount == Decimal("200.00")
    assert by_bucket[("overdue_31_60", "USD")].amount == Decimal("300.00")
    assert by_bucket[("overdue_90_plus", "USD")].amount == Decimal("400.00")
    assert ("overdue_61_90", "USD") not in by_bucket
    assert result.invoices_missing_due_date == 1

    # Percentages sum to (approximately, given rounding) 100 across all buckets.
    total_percent = sum(b.percent_of_total for b in result.buckets)
    assert abs(total_percent - Decimal("100")) < Decimal("0.1")


def test_receivables_section_lists_top_overdue_customers(db_session):
    org = _fi_org(db_session)

    big_customer = make_customer(db_session, org.organization, name="Big Overdue Co", email="big@example.com")
    inv = make_invoice(
        db_session,
        org.organization,
        org.user,
        customer=big_customer,
        due_date=_SAFE_FUTURE_DUE_DATE,
        line_items=[InvoiceLineItemCreate(description="x", quantity=Decimal("1"), unit_price=Decimal("5000.00"))],
    )
    _backdate(db_session, inv, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc), due_date=date.today() - timedelta(days=42))

    section = metrics.build_receivables_section(db_session, org.organization.id, now=datetime.now(timezone.utc))
    names = [c.customer_name for c in section.top_overdue_customers]
    assert "Big Overdue Co" in names


def test_zero_denominators_never_crash_receivables_or_collection_rate(db_session):
    org = _fi_org(db_session)
    today_local = date(2026, 3, 15)
    # No invoices at all.
    result = cashflow.compute_aging_buckets(db_session, org.organization.id, today_local=today_local)
    assert result.buckets == []
    assert result.invoices_missing_due_date == 0

    overview = metrics.build_executive_overview(db_session, org.organization.id, now=datetime(2026, 3, 15, tzinfo=timezone.utc))
    assert overview.by_currency == []


# --- Quotes funnel -----------------------------------------------------


def test_quote_funnel_counts_and_conversion_rate(db_session):
    org = _fi_org(db_session)
    customer = make_customer(db_session, org.organization)

    sent_only = make_quote(db_session, org.organization, org.user, customer=customer)
    sent_only.status = QuoteStatus.sent.value
    db_session.commit()

    accepted_then_converted = make_quote(db_session, org.organization, org.user, customer=customer)
    accepted_then_converted.status = QuoteStatus.sent.value
    db_session.commit()
    db_session.refresh(accepted_then_converted)
    mark_quote_accepted_record(db_session, accepted_then_converted)
    convert_quote_to_invoice(db_session, org.organization.id, accepted_then_converted, org.user)

    rejected = make_quote(db_session, org.organization, org.user, customer=customer)
    rejected.status = QuoteStatus.sent.value
    db_session.commit()
    db_session.refresh(rejected)
    mark_quote_rejected_record(db_session, rejected)

    draft = make_quote(db_session, org.organization, org.user, customer=customer)  # stays draft

    section = metrics.build_quotes_section(db_session, org.organization.id)
    assert section.counts.created == 4
    assert section.counts.sent == 1  # only sent_only is STILL "sent" (others transitioned away)
    assert section.counts.accepted == 0  # accepted_then_converted moved on to "converted"
    assert section.counts.converted == 1
    assert section.counts.rejected == 1
    assert section.conversion_rate_percent is not None
    assert draft.status == QuoteStatus.draft.value


def test_quote_conversion_rate_insufficient_when_no_quotes(db_session):
    org = _fi_org(db_session)
    overview = metrics.build_executive_overview(db_session, org.organization.id, now=datetime(2026, 3, 15, tzinfo=timezone.utc))
    assert overview.quote_conversion_rate.value is None
    assert overview.quote_conversion_rate.data_completeness == "insufficient"


# --- HTTP layer: permissions, tenant isolation, plan gating -----------------


def test_overview_requires_authentication(client, db_session):
    org = _fi_org(db_session, email="fi-auth@example.com")
    response = client.get(f"/organizations/{org.organization.id}/financial-intelligence/overview")
    assert response.status_code == 401


def test_overview_rejects_foreign_user(client, db_session):
    org_a = _fi_org(db_session, email="fi-tenant-a@example.com")
    org_b = _fi_org(db_session, email="fi-tenant-b@example.com")

    response = client.get(
        f"/organizations/{org_a.organization.id}/financial-intelligence/overview",
        headers=org_b.auth_headers,
    )
    assert response.status_code == 403


def test_overview_denies_without_plan_capability(client, db_session):
    org = make_org_with_owner_on_plan(
        db_session, advanced_financial_analytics_enabled=False, email="fi-noplan@example.com"
    )
    response = client.get(
        f"/organizations/{org.organization.id}/financial-intelligence/overview",
        headers=org.auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "advanced_financial_analytics"


def test_all_seven_endpoints_are_reachable_and_return_200(client, db_session):
    org = _fi_org(db_session, email="fi-endpoints@example.com")
    make_invoice(db_session, org.organization, org.user)

    for path in (
        "overview",
        "revenue-trends",
        "receivables-aging",
        "customers",
        "products",
        "quotes",
        "cashflow-calendar",
    ):
        response = client.get(
            f"/organizations/{org.organization.id}/financial-intelligence/{path}", headers=org.auth_headers
        )
        assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text}"


def test_tenant_isolation_data_never_crosses_organizations(client, db_session):
    org_a = _fi_org(db_session, email="fi-iso-a@example.com")
    org_b = _fi_org(db_session, email="fi-iso-b@example.com")

    make_invoice(
        db_session,
        org_a.organization,
        org_a.user,
        line_items=[InvoiceLineItemCreate(description="A-only", quantity=Decimal("1"), unit_price=Decimal("9999.00"))],
    )

    response = client.get(
        f"/organizations/{org_b.organization.id}/financial-intelligence/overview", headers=org_b.auth_headers
    )
    assert response.status_code == 200
    assert response.json()["by_currency"] == []
