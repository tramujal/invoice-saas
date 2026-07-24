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

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.currency import resolve_document_currency_code
from app.email.base import EmailAttachment, EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.email.reminder_templates import (
    build_after_due_reminder_email,
    build_before_due_reminder_email,
    build_due_today_reminder_email,
)
from app.email.templates import build_invoice_email
from app.invoice_numbering import format_invoice_number, parse_invoice_number
from app.invoice_pdf import render_invoice_pdf
from app.models import (
    Customer,
    Invoice,
    InvoiceLineItem,
    InvoiceReminder,
    Organization,
    Product,
    User,
)
from app.org_time import get_organization_today
from app.payment_status import PaymentStatus
from app.reminder_status import ReminderStatus
from app.reminder_type import ReminderType
from app.services.plan_limits import LimitedResource, check_limit
from app.services.products import ProductNotFoundError, get_product_in_org
from app.schemas import (
    CurrencyCode,
    InvoiceLineItemCreate,
    SendInvoiceEmailResponse,
    SendInvoiceReminderResponse,
)

logger = logging.getLogger(__name__)


class InvoiceNotFoundError(Exception):
    """No invoice matches the given reference within this organization."""


class CustomerNotFoundInOrgError(Exception):
    """customer_id doesn't reference a customer in this organization."""


class ProductNotFoundInOrgError(Exception):
    """A line item's product_id doesn't reference a product in this
    organization."""


class CustomerEmailMissingError(Exception):
    """The invoice's customer has no email on file."""


class EmailSendFailedError(Exception):
    """The configured email provider failed to send. Wraps the original
    EmailSendError so callers never need to import app.email.base directly."""


class DueDateBeforeIssueDateError(Exception):
    """The requested due_date is before the organization's local today at
    creation time."""


class RemindersDisabledError(Exception):
    """The organization has not opted into the reminders feature
    (Organization.reminders_enabled == False) -- gates manual/AI-agent
    sends too, not just the scheduled job, so this one toggle is a
    complete kill switch for the whole feature."""


class InvoiceAlreadyPaidError(Exception):
    """The invoice is already paid -- no reminder is ever sent for it."""


class InvoiceDueDateMissingError(Exception):
    """The invoice has no due_date on file, so there is nothing to remind
    about (every historical invoice, and any new invoice created without
    one)."""


class ReminderAlreadySentError(Exception):
    """The unique constraint on (invoice_id, reminder_type,
    scheduled_for_date) already has a row -- this exact reminder slot was
    already claimed, by a scheduled run, an earlier manual click, or the
    AI agent. This is the sole idempotency/concurrency guarantee; nothing
    here is a pre-check race."""


class ReminderSendFailedError(Exception):
    """The configured email provider failed to send this reminder. Wraps
    the original EmailSendError so callers never need to import
    app.email.base directly."""


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
    due_date: date | None = None,
) -> Invoice:
    """The actual DB write: numbering-locked, currency/language pinned at
    creation time. Totals are always recomputed here from `line_items` --
    never accepted as a parameter -- so nothing upstream (including a
    confirmed AI proposal) can hand this function a pre-computed total to
    trust.

    due_date defaults to None (no due date), matching every historical
    invoice -- see Invoice.due_date / app.effective_status. When given, it
    must not be before the organization's local today (see
    app.org_time.get_organization_today); this is the only validation
    performed here, since a due date has no other constraints."""
    check_limit(db, organization_id, LimitedResource.invoices)
    # A line's product_id is purely an analytics tag (see
    # InvoiceLineItem.product_id's docstring) -- validated to resolve
    # within this organization here, but description/quantity/unit_price
    # below always come from `line_items` as given, never re-derived from
    # the live product row. The resolved Product rows are kept (rather than
    # discarded) so their currency_code can feed resolve_document_currency_code
    # below with no extra queries.
    resolved_products_by_id: dict[str, Product] = {}
    for line in line_items:
        if line.product_id is not None:
            try:
                resolved_products_by_id[line.product_id] = get_product_in_org(
                    db, organization_id, line.product_id
                )
            except ProductNotFoundError:
                raise ProductNotFoundInOrgError(line.product_id)

    totals = compute_invoice_totals(line_items, tax_rate)
    line_models = [
        InvoiceLineItem(
            description=line.description,
            quantity=line.quantity,
            unit_price=_quantize_money(line.unit_price),
            line_total=line_total,
            product_id=line.product_id,
        )
        for line, line_total in zip(line_items, totals.line_totals)
    ]

    # Locks the organization row so two concurrent invoice creations can't
    # be handed the same next_invoice_number (a real row lock on Postgres;
    # a harmless no-op on SQLite, which serializes writers itself).
    organization = db.execute(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    ).scalar_one()

    if due_date is not None and due_date < get_organization_today(organization):
        raise DueDateBeforeIssueDateError(due_date)

    invoice_number = organization.next_invoice_number
    organization.next_invoice_number = invoice_number + 1

    # Permanently pinned at creation time -- see Invoice.currency_code's
    # docstring in app/models.py. Neither is ever re-derived later.
    resolved_currency_code = resolve_document_currency_code(
        currency_code.value if currency_code else None,
        line_items,
        resolved_products_by_id,
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
        due_date=due_date,
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


def _hash_for_log(value: str) -> str:
    """Same convention as app.assistant/app.rate_limit -- logs a short,
    non-reversible fingerprint instead of a raw id/email, so log lines are
    correlatable across a run without ever containing PII."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def claim_and_send_reminder(
    db: Session,
    organization: Organization,
    invoice: Invoice,
    reminder_type: ReminderType,
    days_offset: int | None,
    scheduled_for_date: date,
    triggered_by: str,
) -> SendInvoiceReminderResponse:
    """Claim -> re-validate -> send -> update. Shared by the scheduled job
    (app.jobs.send_due_invoice_reminders), the manual "Send reminder"
    button, and the AI agent's propose_send_payment_reminder action --
    exactly one implementation of what counts as an eligible reminder
    send.

    The INSERT below is the entire concurrency/idempotency guarantee: the
    unique constraint on (invoice_id, reminder_type, scheduled_for_date)
    means a conflict (IntegrityError) is proof someone else already
    claimed this exact slot, portable across SQLite and Postgres with no
    dialect-specific ON CONFLICT SQL needed. Manual/AI-agent sends always
    pass reminder_type=manual, scheduled_for_date=today_local, so they
    share one slot per invoice per organization-local calendar day with
    each other -- a second manual click (or agent confirmation) the same
    day always hits this same conflict, not a UI debounce trick.

    Eligibility (not paid, has a due date, customer has an email) is
    re-checked fresh immediately after the claim succeeds, every time --
    never trusted from an earlier lookup -- so a human marking an invoice
    paid a moment before this runs is always respected.
    """
    customer = invoice.customer
    if customer is None or not customer.email:
        raise CustomerEmailMissingError(invoice.id)

    reminder = InvoiceReminder(
        organization_id=organization.id,
        invoice_id=invoice.id,
        reminder_type=reminder_type.value,
        days_offset=days_offset,
        scheduled_for_date=scheduled_for_date,
        recipient_email=customer.email,
        status=ReminderStatus.pending.value,
        triggered_by=triggered_by,
    )
    db.add(reminder)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ReminderAlreadySentError(invoice.id)
    db.refresh(reminder)

    # Fresh re-check, right after the claim -- see the decision this
    # module documents above. Never computed from a stale copy.
    db.refresh(invoice)
    today_local = get_organization_today(organization)

    if invoice.payment_status == PaymentStatus.paid.value:
        reminder.status = ReminderStatus.skipped.value
        reminder.failure_code = "invoice_already_paid"
        db.commit()
        raise InvoiceAlreadyPaidError(invoice.id)

    if invoice.due_date is None:
        reminder.status = ReminderStatus.skipped.value
        reminder.failure_code = "invoice_due_date_missing"
        db.commit()
        raise InvoiceDueDateMissingError(invoice.id)

    days_from_due = (invoice.due_date - today_local).days

    if reminder_type == ReminderType.before_due or (
        reminder_type == ReminderType.manual and days_from_due > 0
    ):
        subject, body = build_before_due_reminder_email(invoice, customer, days_from_due)
    elif reminder_type == ReminderType.after_due or (
        reminder_type == ReminderType.manual and days_from_due < 0
    ):
        subject, body = build_after_due_reminder_email(invoice, customer, -days_from_due)
    else:
        subject, body = build_due_today_reminder_email(invoice, customer)

    email_sender = get_email_sender()
    pdf_bytes = render_invoice_pdf(invoice)
    filename = f"{format_invoice_number(invoice.invoice_number)}.pdf"
    message = EmailMessage(
        to=customer.email,
        subject=subject,
        text_body=body,
        attachments=[EmailAttachment(filename=filename, content=pdf_bytes)],
    )

    logger.info(
        "claim_and_send_reminder: sending organization_id=%s invoice_id=%s "
        "reminder_type=%s triggered_by=%s",
        organization.id,
        invoice.id,
        reminder_type.value,
        triggered_by,
    )

    try:
        email_sender.send(message)
    except EmailSendError as exc:
        reminder.status = ReminderStatus.failed.value
        reminder.failure_code = "reminder_send_failed"
        reminder.attempt_count += 1
        db.commit()
        logger.error(
            "claim_and_send_reminder: failed to send organization_id=%s "
            "invoice_id=%s exception_type=%s exception_message=%s",
            organization.id,
            invoice.id,
            type(exc).__name__,
            str(exc),
        )
        raise ReminderSendFailedError(invoice.id) from exc

    reminder.status = ReminderStatus.sent.value
    reminder.sent_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        "claim_and_send_reminder: sent successfully organization_id=%s invoice_id=%s "
        "reminder_type=%s recipient_hash=%s",
        organization.id,
        invoice.id,
        reminder_type.value,
        _hash_for_log(customer.email),
    )
    return SendInvoiceReminderResponse(
        sent=True, sent_to=customer.email, reminder_type=reminder_type
    )


def send_manual_invoice_reminder(
    db: Session, organization_id: str, invoice: Invoice, triggered_by: str
) -> SendInvoiceReminderResponse:
    """The manual "Send reminder" button and the AI agent's
    propose_send_payment_reminder action both call this -- never the
    scheduled job directly, and never claim_and_send_reminder directly --
    so both share identical gating (reminders_enabled) and the identical
    "manual" idempotency slot for the current organization-local day.
    """
    organization = db.get(Organization, organization_id)
    if organization is None or not organization.reminders_enabled:
        raise RemindersDisabledError(organization_id)

    today_local = get_organization_today(organization)
    return claim_and_send_reminder(
        db,
        organization=organization,
        invoice=invoice,
        reminder_type=ReminderType.manual,
        days_offset=None,
        scheduled_for_date=today_local,
        triggered_by=triggered_by,
    )
