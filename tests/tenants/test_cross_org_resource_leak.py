"""Even a real member of org A must never be able to reach a resource that
belongs to org B by guessing/reusing its id -- every single-resource
lookup filters by organization_id, so this must 404, not 200 (which would
leak the resource's data) and not 403 (which would at least confirm the id
exists somewhere)."""

from decimal import Decimal

from tests.factories import make_customer, make_invoice, make_org_with_owner, make_product, make_quote


def test_customer_from_other_org_is_404(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-a@example.com", org_name="Org A")
    org_b = make_org_with_owner(db_session, email="owner-b@example.com", org_name="Org B")
    customer_b = make_customer(db_session, org_b.organization)

    response = client.patch(
        f"/organizations/{org_a.organization.id}/customers/{customer_b.id}",
        json={"name": "Renamed"},
        headers=org_a.auth_headers,
    )
    assert response.status_code == 404


def test_product_from_other_org_is_404(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-c@example.com", org_name="Org C")
    org_b = make_org_with_owner(db_session, email="owner-d@example.com", org_name="Org D")
    product_b = make_product(db_session, org_b.organization)

    response = client.patch(
        f"/organizations/{org_a.organization.id}/products/{product_b.id}",
        json={"name": "Renamed"},
        headers=org_a.auth_headers,
    )
    assert response.status_code == 404


def test_invoice_from_other_org_is_404(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-e@example.com", org_name="Org E")
    org_b = make_org_with_owner(db_session, email="owner-f@example.com", org_name="Org F")
    invoice_b = make_invoice(db_session, org_b.organization, org_b.user)

    response = client.get(
        f"/organizations/{org_a.organization.id}/invoices/{invoice_b.id}/pdf",
        headers=org_a.auth_headers,
    )
    assert response.status_code == 404


def test_quote_from_other_org_is_404(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-g@example.com", org_name="Org G")
    org_b = make_org_with_owner(db_session, email="owner-h@example.com", org_name="Org H")
    quote_b = make_quote(db_session, org_b.organization, org_b.user)

    response = client.get(
        f"/organizations/{org_a.organization.id}/quotes/{quote_b.id}",
        headers=org_a.auth_headers,
    )
    assert response.status_code == 404


def test_quote_convert_across_orgs_is_404_not_leaked(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-i@example.com", org_name="Org I")
    org_b = make_org_with_owner(db_session, email="owner-j@example.com", org_name="Org J")
    quote_b = make_quote(db_session, org_b.organization, org_b.user)

    response = client.post(
        f"/organizations/{org_a.organization.id}/quotes/{quote_b.id}/convert",
        headers=org_a.auth_headers,
    )
    assert response.status_code == 404


def test_member_row_from_other_org_is_404(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-k@example.com", org_name="Org K")
    org_b = make_org_with_owner(db_session, email="owner-l@example.com", org_name="Org L")

    response = client.patch(
        f"/organizations/{org_a.organization.id}/members/{org_b.membership.id}",
        json={"role": "admin"},
        headers=org_a.auth_headers,
    )
    assert response.status_code == 404
