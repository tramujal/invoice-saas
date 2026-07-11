"""Shared invoice business logic.

Extracted from app.routers.invoices so the exact same create/update-status/
send-email behavior is used by both the direct HTTP endpoints and the AI
assistant's action tools (see app/ai/tools/invoices.py) -- exactly one
implementation of each, never two that could silently drift apart. Every
function here takes organization_id (or an already org-scoped Invoice/
Customer row) explicitly and never trusts a caller-supplied id without
filtering on it, matching every other tenant-isolation boundary in this
codebase.

Raises small, typed exceptions instead of HTTPException so this module has
no FastAPI dependency and both call sites (a router, which maps them to
HTTP status codes, and a tool, which maps them to assistant error codes)
can translate them independently.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.currency import resolve_default_currency_code
from app.email.base import EmailAttachment, EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.email.templates import build_invoice_email
from app.invoice_numbering import format_invoice_number, parse_invoice_number
from app.invoice_pdf import render_invoice_pdf
from app.models import Customer, Invoice, InvoiceLineItem, Organization, User
from app.payment_status import PaymentStatus
from app.schemas import CurrencyCode, InvoiceLineItemCreate, SendInvoiceEmailResponse

logger = logging.getLogger(__name__)


class InvoiceNotFoundError(Exception):
    """No invoice matches the given reference within this organization."""


class CustomerNotFoundInOrgError(Exception):
    """customer_id doesn't reference a customer in this organization."""


class CustomerEmailMissingError(Exception):
    """The invoice's customer has no email on file."""


class EmailSendFailedError(Exception):
    """The configured email provider failed to send. Wraps the original
    EmailSendError so callers never need to import app.email.base directly."""


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


@dataclass
class InvoiceTotals:
    line_totals: list[Decimal]
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal


def compute_invoice_totals(
    line_items: list[InvoiceLineItemCreate], tax_rate: Decimal
) -> InvoiceTotals:
    """Pure -- no DB access, no invoice-number consumption. Used both for
    the real write (create_invoice_record) and for building an AI action
    proposal's preview summary, so a preview's numbers are guaranteed
    identical to what execution will actually produce, and a proposal is
    never persisted with numbers the model supplied itself."""
    line_totals: list[Decimal] = []
    subtotal = Decimal("0")
    for line in line_items:
        line_total = _quantize_money(line.quantity * line.unit_price)
        line_totals.append(line_total)
        subtotal += line_total

    subtotal = _quantize_money(subtotal)
    tax_amount = _quantize_money(subtotal * tax_rate)
    total = _quantize_money(subtotal + tax_amount)
    return InvoiceTotals(
        line_totals=line_totals, subtotal=subtotal, tax_amount=tax_amount, total=total
    )


def get_customer_in_org(db: Session, organization_id: str, customer_id: str) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
        )
    )
    if customer is None:
        raise CustomerNotFoundInOrgError(customer_id)
    return customer


def create_invoice_record(
    db: Session,
    organization_id: str,
    current_user: User,
    customer: Customer | None,
    currency_code: CurrencyCode | None,
    line_items: list[InvoiceLineItemCreate],
    tax_rate: Decimal,
) -> Invoice:
    """The actual DB write: numbering-locked, currency/language pinned at
    creation time. Totals are always recomputed here from `line_items` --
    never accepted as a parameter -- so nothing upstream (including a
    confirmed AI proposal) can hand this function a pre-computed total to
    trust."""
    totals = compute_invoice_totals(line_items, tax_rate)
    line_models = [
        InvoiceLineItem(
            description=line.description,
            quantity=line.quantity,
            unit_price=_quantize_money(line.unit_price),
            line_total=line_total,
        )
        for line, line_total in zip(line_items, totals.line_totals)
    ]

    # Locks the organization row so two concurrent invoice creations can't
    # be handed the same next_invoice_number (a real row lock on Postgres;
    # a harmless no-op on SQLite, which serializes writers itself).
    organization = db.execute(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    ).scalar_one()
    invoice_number = organization.next_invoice_number
    organization.next_invoice_number = invoice_number + 1

    # Permanently pinned at creation time -- see Invoice.currency_code's
    # docstring in app/models.py. Neither is ever re-derived later.
    resolved_currency_code = (
        currency_code.value
        if currency_code
        else resolve_default_currency_code(customer, organization)
    )
    language = organization.language

    invoice = Invoice(
        organization_id=organization_id,
        invoice_number=invoice_number,
        created_by_user_id=current_user.id,
        customer_id=customer.id if customer else None,
        subtotal=totals.subtotal,
        tax_amount=totals.tax_amount,
        total=totals.total,
        currency_code=resolved_currency_code,
        language=language,
        line_items=line_models,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def get_invoice_in_org(db: Session, organization_id: str, invoice_reference: str) -> Invoice:
    """Resolves an invoice scoped to organization_id, by raw id OR a human
    invoice reference ("INV-000023", "23", "000023"). Shared by the direct
    HTTP endpoints (which pass a raw id from the URL path) and the AI
    assistant's tools (which pass whatever reference the user/model typed)
    -- exactly one lookup implementation, exactly one org filter, so an
    invoice from another organization can never be resolved by either
    caller."""
    parsed_number = parse_invoice_number(invoice_reference)
    if parsed_number is not None:
        invoice = db.scalar(
            select(Invoice).where(
                Invoice.organization_id == organization_id,
                Invoice.invoice_number == parsed_number,
            )
        )
        if invoice is not None:
            return invoice

    invoice = db.scalar(
        select(Invoice).where(
            Invoice.id == invoice_reference,
            Invoice.organization_id == organization_id,
        )
    )
    if invoice is None:
        raise InvoiceNotFoundError(invoice_reference)
    return invoice


def update_invoice_payment_status_record(
    db: Session, invoice: Invoice, new_status: PaymentStatus
) -> Invoice:
    invoice.payment_status = new_status.value
    db.commit()
    db.refresh(invoice)
    return invoice


def send_invoice_email_record(db: Session, invoice: Invoice) -> SendInvoiceEmailResponse:
    customer = invoice.customer
    if customer is None or not customer.email:
        raise CustomerEmailMissingError(invoice.id)

    email_sender = get_email_sender()
    pdf_bytes = render_invoice_pdf(invoice)
    filename = f"{format_invoice_number(invoice.invoice_number)}.pdf"
    subject, body = build_invoice_email(invoice, customer)

    message = EmailMessage(
        to=customer.email,
        subject=subject,
        text_body=body,
        attachments=[EmailAttachment(filename=filename, content=pdf_bytes)],
    )

    logger.info(
        "send_invoice_email_record: sending invoice email organization_id=%s invoice_id=%s",
        invoice.organization_id,
        invoice.id,
    )

    try:
        email_sender.send(message)
    except EmailSendError as exc:
        # Full exception detail is already logged at the source
        # (resend_provider's own logger.exception call). This line adds the
        # business context (which org/invoice) so the two log lines can be
        # correlated -- callers only ever get EmailSendFailedError, never
        # str(exc), which could leak the provider's raw error text.
        logger.error(
            "send_invoice_email_record: failed to send invoice email "
            "organization_id=%s invoice_id=%s exception_type=%s exception_message=%s",
            invoice.organization_id,
            invoice.id,
            type(exc).__name__,
            str(exc),
        )
        raise EmailSendFailedError(invoice.id) from exc

    logger.info(
        "send_invoice_email_record: invoice email sent successfully "
        "organization_id=%s invoice_id=%s",
        invoice.organization_id,
        invoice.id,
    )
    return SendInvoiceEmailResponse(sent=True, sent_to=customer.email)
