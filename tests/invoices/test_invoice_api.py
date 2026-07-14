from datetime import date, timedelta

from tests.factories import make_customer, make_org_with_owner


def test_create_invoice_via_api(client, db_session):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    customer = make_customer(db_session, owner.organization)

    response = client.post(
        f"/organizations/{owner.organization.id}/invoices",
        json={
            "line_items": [
                {"description": "Design work", "quantity": "3", "unit_price": "40.00"}
            ],
            "customer_id": customer.id,
            "due_date": str(date.today() + timedelta(days=14)),
            "currency_code": "USD",
        },
        headers=owner.auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["total"] == "120.00"


def test_create_invoice_rejects_due_date_before_today(client, db_session):
    owner = make_org_with_owner(db_session, email="owner2@example.com")

    response = client.post(
        f"/organizations/{owner.organization.id}/invoices",
        json={
            "line_items": [{"description": "Work", "quantity": "1", "unit_price": "10.00"}],
            "due_date": str(date.today() - timedelta(days=1)),
        },
        headers=owner.auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "due_date_before_issue_date"


def test_download_invoice_pdf(client, db_session):
    from tests.factories import make_invoice

    owner = make_org_with_owner(db_session, email="owner3@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user)

    response = client.get(
        f"/organizations/{owner.organization.id}/invoices/{invoice.id}/pdf",
        headers=owner.auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


def test_send_invoice_email_uses_fake_sender(client, db_session, fake_email_sender):
    from tests.factories import make_invoice

    owner = make_org_with_owner(db_session, email="owner4@example.com")
    customer = make_customer(db_session, owner.organization, email="billed@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user, customer=customer)

    response = client.post(
        f"/organizations/{owner.organization.id}/invoices/{invoice.id}/send-email",
        headers=owner.auth_headers,
    )
    assert response.status_code == 200
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "billed@example.com"
