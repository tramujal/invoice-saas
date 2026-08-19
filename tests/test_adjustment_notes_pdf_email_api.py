"""Phase 29 Pass 2 -- HTTP surface for note PDF/send, and the new
single-invoice GET endpoint the detail page depends on.
"""

from decimal import Decimal

import pytest

from app.schemas import InvoiceLineItemCreate
from tests.factories import make_customer, make_invoice, make_org_with_owner


def inv_line(desc, qty, price, rate="0"):
    return InvoiceLineItemCreate(
        description=desc, quantity=Decimal(qty), unit_price=Decimal(price), tax_rate=Decimal(rate)
    )


@pytest.fixture
def setup(db_session):
    owner = make_org_with_owner(db_session, email="api-pdf@example.com", org_name="API PDF Co")
    customer = make_customer(db_session, owner.organization, email="c@example.com")
    invoice = make_invoice(
        db_session, owner.organization, owner.user, customer=customer,
        line_items=[inv_line("A", "1", "1000.00", "0.22")], tax_rate=Decimal("0"),
    )
    return owner, invoice


def base(owner):
    return f"/organizations/{owner.organization.id}"


def create_and_issue(client, owner, invoice, amount="500.00"):
    r = client.post(
        f"{base(owner)}/invoices/{invoice.id}/adjustment-notes/credit",
        json={
            "line_items": [{"description": "Refund", "quantity": "1", "unit_price": amount, "tax_rate": "0.22"}],
            "issue_immediately": True,
        },
        headers=owner.auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- GET /invoices/{id} -------------------------------------------------


def test_get_single_invoice(client, db_session, setup):
    owner, invoice = setup
    r = client.get(f"{base(owner)}/invoices/{invoice.id}", headers=owner.auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == invoice.id
    assert body["tax_groups"]
    assert len(body["line_items"]) == 1


def test_get_single_invoice_cross_tenant_is_404(client, db_session, setup):
    owner, invoice = setup
    outsider = make_org_with_owner(db_session, email="out-pdf@example.com", org_name="Outsider PDF")
    r = client.get(f"/organizations/{outsider.organization.id}/invoices/{invoice.id}", headers=outsider.auth_headers)
    assert r.status_code == 404


# --- PDF -----------------------------------------------------------------


def test_download_note_pdf(client, db_session, setup):
    owner, invoice = setup
    note = create_and_issue(client, owner, invoice)
    r = client.get(f"{base(owner)}/adjustment-notes/{note['id']}/pdf", headers=owner.auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert note["note_number"] in r.headers["content-disposition"]


def test_download_draft_note_pdf_is_allowed(client, db_session, setup):
    owner, invoice = setup
    r = client.post(
        f"{base(owner)}/invoices/{invoice.id}/adjustment-notes/credit",
        json={"line_items": [{"description": "Draft", "quantity": "1", "unit_price": "10.00"}]},
        headers=owner.auth_headers,
    )
    note_id = r.json()["id"]
    pdf = client.get(f"{base(owner)}/adjustment-notes/{note_id}/pdf", headers=owner.auth_headers)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_pdf_requires_read_permission_and_is_tenant_scoped(client, db_session, setup):
    owner, invoice = setup
    outsider = make_org_with_owner(db_session, email="out-pdf2@example.com", org_name="Outsider PDF 2")
    note = create_and_issue(client, owner, invoice)
    r = client.get(
        f"/organizations/{outsider.organization.id}/adjustment-notes/{note['id']}/pdf",
        headers=outsider.auth_headers,
    )
    assert r.status_code == 404


# --- send-email ------------------------------------------------------------


def test_send_email_requires_issued(client, db_session, setup):
    owner, invoice = setup
    r = client.post(
        f"{base(owner)}/invoices/{invoice.id}/adjustment-notes/credit",
        json={"line_items": [{"description": "Draft", "quantity": "1", "unit_price": "10.00"}]},
        headers=owner.auth_headers,
    )
    note_id = r.json()["id"]
    send = client.post(f"{base(owner)}/adjustment-notes/{note_id}/send-email", headers=owner.auth_headers)
    assert send.status_code == 409
    assert send.json()["detail"]["code"] == "note_not_sendable"


def test_send_email_without_configured_provider_is_503(client, db_session, setup):
    """The test environment has no RESEND_API_KEY configured. get_email_sender()
    itself raises the "not configured" HTTPException (503), the exact
    same behavior app.routers.invoices relies on for invoice sending --
    this endpoint reaches the real, shared EmailSender abstraction rather
    than a stub, and does not swallow or reinterpret that error."""
    owner, invoice = setup
    note = create_and_issue(client, owner, invoice)
    r = client.post(f"{base(owner)}/adjustment-notes/{note['id']}/send-email", headers=owner.auth_headers)
    assert r.status_code == 503, r.text
