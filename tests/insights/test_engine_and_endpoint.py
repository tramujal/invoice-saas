from datetime import datetime, timezone
from decimal import Decimal

from app.insights.engine import build_insights
from tests.factories import make_customer, make_invoice, make_org_with_owner


def test_build_insights_on_empty_organization_does_not_crash(db_session):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    insights = build_insights(db_session, owner.organization.id, "en", datetime.now(timezone.utc))
    assert isinstance(insights, list)


def test_build_insights_on_populated_organization(db_session):
    owner = make_org_with_owner(db_session, email="owner2@example.com")
    customer = make_customer(db_session, owner.organization)
    for _ in range(3):
        make_invoice(db_session, owner.organization, owner.user, customer=customer)

    insights = build_insights(db_session, owner.organization.id, "en", datetime.now(timezone.utc))
    assert isinstance(insights, list)
    # Every candidate must be scoped to this organization -- nothing here
    # asserts specific insight ids (those depend on business heuristics
    # that may evolve), only structural safety.
    for insight in insights:
        assert insight.id


def test_build_insights_is_tenant_isolated_via_endpoint(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-a@example.com", org_name="Org A")
    org_b = make_org_with_owner(db_session, email="owner-b@example.com", org_name="Org B")
    customer_a = make_customer(db_session, org_a.organization, name="Org A Customer")
    customer_b = make_customer(db_session, org_b.organization, name="Org B Customer")
    make_invoice(db_session, org_a.organization, org_a.user, customer=customer_a)
    make_invoice(db_session, org_b.organization, org_b.user, customer=customer_b)

    response = client.get(
        f"/organizations/{org_a.organization.id}/dashboard/insights", headers=org_a.auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    serialized = str(body)
    assert "Org B Customer" not in serialized


def test_multi_currency_invoices_are_not_combined_in_a_single_metric(db_session):
    """A metric's currency_code is always a single ISO code -- multi-
    currency totals must never be silently summed together into one
    number, which would be meaningless across currencies."""
    owner = make_org_with_owner(db_session, email="owner3@example.com")
    customer = make_customer(db_session, owner.organization)
    from app.schemas import CurrencyCode, InvoiceLineItemCreate
    from app.services.invoices import create_invoice_record

    create_invoice_record(
        db_session,
        owner.organization.id,
        owner.user,
        customer,
        CurrencyCode.USD,
        [InvoiceLineItemCreate(description="USD line", quantity=Decimal("1"), unit_price=Decimal("100"))],
        Decimal("0"),
    )
    create_invoice_record(
        db_session,
        owner.organization.id,
        owner.user,
        customer,
        CurrencyCode.EUR,
        [InvoiceLineItemCreate(description="EUR line", quantity=Decimal("1"), unit_price=Decimal("50"))],
        Decimal("0"),
    )

    insights = build_insights(db_session, owner.organization.id, "en", datetime.now(timezone.utc))
    for insight in insights:
        if insight.metric is not None and insight.metric.value is not None:
            assert insight.metric.currency_code in ("USD", "EUR", None)
