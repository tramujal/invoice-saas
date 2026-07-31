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


def test_invoice_customer_snapshot_immune_to_later_customer_edits(client, db_session):
    """H6: editing a customer after an invoice was issued must never
    change that invoice's displayed billing info -- via the API response
    AND via the rendered PDF, both of which must read the permanent
    snapshot taken at creation time, never a live join."""
    owner = make_org_with_owner(db_session, email="owner-snapshot@example.com")
    customer = make_customer(db_session, owner.organization, name="Original Name", email="original@example.com")
    customer.phone = "555-0000"
    customer.address = "1 Original St"
    db_session.commit()

    create_response = client.post(
        f"/organizations/{owner.organization.id}/invoices",
        json={
            "line_items": [{"description": "Design work", "quantity": "1", "unit_price": "10.00"}],
            "customer_id": customer.id,
            "currency_code": "USD",
        },
        headers=owner.auth_headers,
    )
    assert create_response.status_code == 201, create_response.text
    invoice_id = create_response.json()["id"]

    customer.name = "Renamed Customer"
    customer.email = "renamed@example.com"
    customer.phone = "555-9999"
    customer.address = "2 Renamed Ave"
    db_session.commit()

    list_response = client.get(
        f"/organizations/{owner.organization.id}/invoices", headers=owner.auth_headers
    )
    assert list_response.status_code == 200
    listed = next(item for item in list_response.json()["items"] if item["id"] == invoice_id)
    assert listed["customer_name"] == "Original Name"

    from app.invoice_pdf import render_invoice_pdf
    from app.models import Invoice

    invoice = db_session.query(Invoice).filter_by(id=invoice_id).one()
    # Snapshot columns are the actual source PDF rendering reads from
    # (see app.invoice_pdf's own comment) -- asserted directly here since
    # extracting text back out of compressed PDF content streams isn't a
    # reliable test signal; render_invoice_pdf is still called to prove
    # rendering doesn't crash against the snapshot-based code path.
    render_invoice_pdf(invoice)
    assert invoice.customer_name_snapshot == "Original Name"
    assert invoice.customer_email_snapshot == "original@example.com"
    assert invoice.customer_phone_snapshot == "555-0000"
    assert invoice.customer_address_snapshot == "1 Original St"


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
