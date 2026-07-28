"""app.analytics.calculators.payments -- documents, and asserts, that
average payment time is honestly unavailable today (Invoice has no
paid_at timestamp). This is the one calculator in this package whose
correct behavior IS to always report unavailable -- see that module's
own docstring."""

from app.analytics.calculators.payments import get_average_payment_time
from tests.factories import make_invoice, make_org_with_owner


def test_reports_unavailable_with_a_reason(db_session):
    org = make_org_with_owner(db_session, email="payment-time@example.com")
    make_invoice(db_session, org.organization, org.user)

    result = get_average_payment_time(db_session, org.organization.id)
    assert result.available is False
    assert result.average_days is None
    assert result.reason is not None and "paid_at" in result.reason
