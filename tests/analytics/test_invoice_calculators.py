from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.analytics.calculators.invoices import (
    get_average_invoice_value,
    get_invoice_counts,
    get_monthly_invoice_counts,
    get_pending_by_currency,
)
from app.analytics.time_windows import TimeWindowKind, resolve_time_window
from app.models import Invoice
from app.payment_status import PaymentStatus
from app.schemas import CurrencyCode
from tests.factories import make_invoice, make_org_with_owner


def _insert_invoices_directly(db_session, organization, count: int) -> None:
    """Bulk-inserts plain Invoice rows via the ORM, bypassing
    create_invoice_record (and therefore plan-limit enforcement, which
    the free plan's monthly invoice cap would otherwise hit well before
    a meaningful "large dataset" size). Appropriate here specifically
    because this test is about SQL-side aggregation correctness at scale,
    not invoice-creation business rules -- those are covered by
    tests/invoices/ and tests/test_plan_limits.py."""
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


class TestGetInvoiceCounts:
    def test_empty_dataset(self, db_session):
        org = make_org_with_owner(db_session, email="inv-empty@example.com")
        counts = get_invoice_counts(db_session, org.organization.id)
        assert counts.total == 0
        assert counts.pending == 0
        assert counts.paid == 0
        assert counts.overdue == 0

    def test_single_invoice_defaults_to_pending(self, db_session):
        org = make_org_with_owner(db_session, email="inv-single@example.com")
        make_invoice(db_session, org.organization, org.user)
        counts = get_invoice_counts(db_session, org.organization.id)
        assert counts.total == 1
        assert counts.pending == 1
        assert counts.paid == 0
        assert counts.overdue == 0

    def test_uses_effective_status_not_raw_stored_column(self, db_session):
        """An invoice whose due_date has passed is counted as overdue even
        if payment_status was never explicitly updated -- the same
        due-date-derived rule every other surface in this app follows.
        create_invoice_record rejects a past due_date outright, so the
        past date is set directly on the row afterward, the same
        after-the-fact-mutation pattern this suite's siblings use for
        backdating created_at."""
        org = make_org_with_owner(db_session, email="inv-effective@example.com")
        invoice = make_invoice(db_session, org.organization, org.user)
        invoice.due_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
        db_session.commit()

        counts = get_invoice_counts(db_session, org.organization.id)
        assert counts.overdue == 1
        assert counts.pending == 0

    def test_paid_status_wins_regardless_of_due_date(self, db_session):
        org = make_org_with_owner(db_session, email="inv-paid@example.com")
        invoice = make_invoice(db_session, org.organization, org.user)
        invoice.due_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
        invoice.payment_status = PaymentStatus.paid.value
        db_session.commit()

        counts = get_invoice_counts(db_session, org.organization.id)
        assert counts.paid == 1
        assert counts.overdue == 0

    def test_window_filters_by_created_at(self, db_session):
        org = make_org_with_owner(db_session, email="inv-window@example.com")
        old = make_invoice(db_session, org.organization, org.user)
        old.created_at = datetime.now(timezone.utc) - timedelta(days=60)
        db_session.commit()
        make_invoice(db_session, org.organization, org.user)  # created "now"

        window = resolve_time_window(TimeWindowKind.last_30_days)
        counts = get_invoice_counts(db_session, org.organization.id, window=window)
        assert counts.total == 1

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="inv-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="inv-tenant-b@example.com")
        make_invoice(db_session, org_a.organization, org_a.user)
        make_invoice(db_session, org_b.organization, org_b.user)
        make_invoice(db_session, org_b.organization, org_b.user)

        assert get_invoice_counts(db_session, org_a.organization.id).total == 1
        assert get_invoice_counts(db_session, org_b.organization.id).total == 2

    def test_large_dataset(self, db_session):
        org = make_org_with_owner(db_session, email="inv-large@example.com")
        _insert_invoices_directly(db_session, org.organization, 250)
        assert get_invoice_counts(db_session, org.organization.id).total == 250


class TestGetAverageInvoiceValue:
    def test_empty_dataset_returns_empty_dict(self, db_session):
        org = make_org_with_owner(db_session, email="avg-empty@example.com")
        assert get_average_invoice_value(db_session, org.organization.id) == {}

    def test_single_invoice(self, db_session):
        org = make_org_with_owner(db_session, email="avg-single@example.com")
        make_invoice(db_session, org.organization, org.user)  # $100 line item, no tax
        result = get_average_invoice_value(db_session, org.organization.id)
        assert result == {"USD": Decimal("100.00")}

    def test_multiple_currencies_never_averaged_together(self, db_session):
        org = make_org_with_owner(db_session, email="avg-multi@example.com")
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.USD)
        make_invoice(db_session, org.organization, org.user, currency_code=CurrencyCode.EUR)

        result = get_average_invoice_value(db_session, org.organization.id)
        assert set(result.keys()) == {"USD", "EUR"}
        assert result["USD"] == Decimal("100.00")
        assert result["EUR"] == Decimal("100.00")

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="avg-tenant-a@example.com")
        org_b = make_org_with_owner(db_session, email="avg-tenant-b@example.com")
        make_invoice(db_session, org_a.organization, org_a.user)

        assert get_average_invoice_value(db_session, org_b.organization.id) == {}


class TestGetPendingByCurrency:
    def test_uses_raw_stored_status_not_effective_status(self, db_session):
        """Deliberately different from get_invoice_counts: an invoice
        whose due date has passed but whose stored payment_status is
        still literally "pending" is still counted here -- preserving the
        exact legacy semantics of the pre-Phase-16A
        get_pending_total_by_currency helper. See this module's own
        docstring."""
        org = make_org_with_owner(db_session, email="pending-raw@example.com")
        invoice = make_invoice(db_session, org.organization, org.user)
        invoice.due_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
        db_session.commit()

        result = get_pending_by_currency(db_session, org.organization.id)
        assert result == {"USD": Decimal("100.00")}

    def test_paid_invoices_excluded(self, db_session):
        org = make_org_with_owner(db_session, email="pending-paid@example.com")
        invoice = make_invoice(db_session, org.organization, org.user)
        invoice.payment_status = PaymentStatus.paid.value
        db_session.commit()

        assert get_pending_by_currency(db_session, org.organization.id) == {}


class TestGetMonthlyInvoiceCounts:
    def test_zero_fills_months_with_no_invoices(self, db_session):
        org = make_org_with_owner(db_session, email="monthly-zero@example.com")
        make_invoice(db_session, org.organization, org.user)
        now = datetime.now(timezone.utc)
        month_starts = [now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]

        result = get_monthly_invoice_counts(db_session, org.organization.id, month_starts)
        assert len(result) == 1
        assert result[0][1] == 1
