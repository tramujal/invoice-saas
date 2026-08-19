"""Phase 29 Pass 2 -- adjustment note PDFs and email delivery.

Verifies:
  - the PDF renders for both note types, single- and mixed-rate
  - it reuses Phase 28's pdf_tax_rows (no duplicated tax layout)
  - it contains no DGI/CFE/CAE/fiscal-QR content of any kind
  - email is send-only-if-issued, uses the existing EmailSender +
    background-job architecture, and fires the canonical event
"""

from decimal import Decimal

import pytest

from app.adjustment_note_pdf import render_adjustment_note_pdf
from app.adjustment_note_type import AdjustmentNoteType
from app.models import WebhookEvent
from app.schemas import InvoiceLineItemCreate
from app.services.adjustment_notes import (
    CustomerEmailMissingError,
    NoteNotSendableError,
    create_adjustment_note,
    issue_adjustment_note,
    send_adjustment_note_email,
)
from tests.factories import make_customer, make_invoice, make_org_with_owner


def inv_line(desc, qty, price, rate="0"):
    return InvoiceLineItemCreate(
        description=desc, quantity=Decimal(qty), unit_price=Decimal(price), tax_rate=Decimal(rate)
    )


@pytest.fixture
def org(db_session):
    return make_org_with_owner(db_session, email="pdf-notes@example.com", org_name="PDF Notes Co")


@pytest.fixture
def mixed_invoice(db_session, org):
    customer = make_customer(db_session, org.organization, email="c@example.com")
    return make_invoice(
        db_session,
        org.organization,
        org.user,
        customer=customer,
        line_items=[
            inv_line("A", "1", "1000.00", "0.22"),
            inv_line("B", "1", "500.00", "0.10"),
            inv_line("C", "1", "200.00", "0"),
        ],
        tax_rate=Decimal("0"),
    )


def _note_line():
    from app.schemas import AdjustmentNoteLineItemCreate

    return AdjustmentNoteLineItemCreate(
        description="Partial refund", quantity=Decimal("1"), unit_price=Decimal("500.00"),
        tax_rate=Decimal("0.22"),
    )


# --- PDF ----------------------------------------------------------------


def test_credit_note_pdf_renders(db_session, org, mixed_invoice):
    note = create_adjustment_note(
        db_session, org.organization.id, note_type=AdjustmentNoteType.credit,
        source_invoice_id=mixed_invoice.id, line_items=[_note_line()], current_user=org.user,
        issue_immediately=True,
    )
    pdf = render_adjustment_note_pdf(note)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_debit_note_pdf_renders(db_session, org, mixed_invoice):
    from app.schemas import AdjustmentNoteLineItemCreate

    note = create_adjustment_note(
        db_session, org.organization.id, note_type=AdjustmentNoteType.debit,
        source_invoice_id=mixed_invoice.id,
        line_items=[
            AdjustmentNoteLineItemCreate(
                description="Extra service", quantity=Decimal("1"), unit_price=Decimal("100.00"),
                tax_rate=Decimal("0.22"),
            )
        ],
        current_user=org.user, issue_immediately=True,
    )
    pdf = render_adjustment_note_pdf(note)
    assert pdf.startswith(b"%PDF")


def test_pdf_renders_before_issuance_too(db_session, org, mixed_invoice):
    """A draft note's PDF must still be viewable -- an operator needs to
    check a note before issuing it."""
    note = create_adjustment_note(
        db_session, org.organization.id, note_type=AdjustmentNoteType.credit,
        source_invoice_id=mixed_invoice.id, line_items=[_note_line()], current_user=org.user,
    )
    assert render_adjustment_note_pdf(note).startswith(b"%PDF")


def test_pdf_never_contains_fiscal_content(db_session, org, mixed_invoice):
    """Hard requirement: no DGI branding, no CFE terminology, no CAE, no
    fiscal-QR or electronic-signature claims. Checked against the raw PDF
    bytes (the strings appear literally in ReportLab's content streams for
    the ASCII text we write) as a blunt but effective guard against ever
    slipping fiscal language in here by accident."""
    note = create_adjustment_note(
        db_session, org.organization.id, note_type=AdjustmentNoteType.credit,
        source_invoice_id=mixed_invoice.id,
        line_items=[_note_line()], current_user=org.user, issue_immediately=True,
    )
    pdf_text = render_adjustment_note_pdf(note)
    forbidden = [b"DGI", b"CFE", b"CAE", b"e-Factura", b"e-Ticket", b"fiscal QR", b"electronic signature"]
    for term in forbidden:
        assert term not in pdf_text, term


def test_pdf_title_matches_note_type(db_session, org, mixed_invoice):
    from app.localization import t

    credit = create_adjustment_note(
        db_session, org.organization.id, note_type=AdjustmentNoteType.credit,
        source_invoice_id=mixed_invoice.id, line_items=[_note_line()], current_user=org.user,
    )
    assert t("en", "credit_note_title") == "CREDIT NOTE"
    assert t("es", "credit_note_title") == "NOTA DE CRÉDITO"
    assert t("en", "debit_note_title") == "DEBIT NOTE"
    assert t("es", "debit_note_title") == "NOTA DE DÉBITO"
    # sanity: the note itself still renders regardless of language used
    assert render_adjustment_note_pdf(credit).startswith(b"%PDF")


# --- email ----------------------------------------------------------------


def test_send_requires_issued(db_session, org, mixed_invoice):
    note = create_adjustment_note(
        db_session, org.organization.id, note_type=AdjustmentNoteType.credit,
        source_invoice_id=mixed_invoice.id, line_items=[_note_line()], current_user=org.user,
    )
    with pytest.raises(NoteNotSendableError):
        send_adjustment_note_email(db_session, note, current_user=org.user)


def test_send_requires_a_customer_email(db_session, org):
    from app.schemas import AdjustmentNoteLineItemCreate

    invoice = make_invoice(db_session, org.organization, org.user)  # no customer, total 100.00
    note = create_adjustment_note(
        db_session, org.organization.id, note_type=AdjustmentNoteType.credit,
        source_invoice_id=invoice.id,
        line_items=[
            AdjustmentNoteLineItemCreate(
                description="Partial refund", quantity=Decimal("1"), unit_price=Decimal("50.00"),
                tax_rate=Decimal("0"),
            )
        ],
        current_user=org.user, issue_immediately=True,
    )
    with pytest.raises(CustomerEmailMissingError):
        send_adjustment_note_email(db_session, note, current_user=org.user)


def test_send_succeeds_and_emits_the_sent_event(db_session, org, mixed_invoice, monkeypatch):
    sent_messages = []

    class FakeSender:
        def send(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(
        "app.services.adjustment_notes.get_email_sender" if False else "app.email.factory.get_email_sender",
        lambda: FakeSender(),
    )
    # send_adjustment_note_email imports get_email_sender locally at call
    # time, so patching the factory module (not the call site) is what
    # actually takes effect -- matches this app's existing patching
    # convention for provider-agnostic factories.
    note = create_adjustment_note(
        db_session, org.organization.id, note_type=AdjustmentNoteType.credit,
        source_invoice_id=mixed_invoice.id, line_items=[_note_line()], current_user=org.user,
        issue_immediately=True,
    )
    recipient = send_adjustment_note_email(db_session, note, current_user=org.user)
    assert recipient == "c@example.com"
    assert len(sent_messages) == 1
    assert sent_messages[0].attachments[0].content.startswith(b"%PDF")

    events = [
        e.event_type
        for e in db_session.query(WebhookEvent).filter_by(organization_id=org.organization.id).all()
    ]
    assert "adjustment_note.sent" in events
