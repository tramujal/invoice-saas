"""Shared quote business logic.

Mirrors app.services.invoices's own rationale: extracted so the exact
same create/update/duplicate/accept/reject/convert/send behavior is used
by both the direct HTTP endpoints (app/routers/quotes.py,
app/routers/quote_public.py) and the AI assistant's action tools
(app/ai/tools/quotes.py) -- exactly one implementation of each, never two
that could silently drift apart.

Totals math is never re-implemented here: compute_invoice_totals (from
app.services.invoices) is reused as-is, since it's already a pure function
of line items + tax rate with nothing invoice-specific about it. Quote to
Invoice conversion reuses create_invoice_record (also from
app.services.invoices) completely unchanged, which is what guarantees the
resulting invoice is fully independent -- fresh line items, fresh
numbering, no stored reference back to the quote.

Raises small, typed exceptions instead of HTTPException, matching
app.services.invoices's own convention (no FastAPI dependency; each caller
translates independently).
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.currency import resolve_document_currency_code
from app.email.base import EmailAttachment, EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.email.quote_templates import build_quote_email, build_quote_reminder_email
from app.models import (
    Customer,
    Invoice,
    Organization,
    Product,
    Quote,
    QuoteLineItem,
    QuoteReminder,
    User,
)
from app.org_time import get_organization_today
from app.quote_effective_status import get_effective_quote_status
from app.quote_numbering import format_quote_number, parse_quote_number
from app.quote_pdf import render_quote_pdf
from app.quote_public_links import build_quote_public_link, generate_quote_public_token
from app.quote_status import QuoteStatus
from app.reminder_status import ReminderStatus
from app.services.invoices import compute_invoice_totals, create_invoice_record
from app.services.products import ProductNotFoundError, get_product_in_org
from app.schemas import CurrencyCode, InvoiceLineItemCreate, QuoteLineItemCreate, SendQuoteEmailResponse

logger = logging.getLogger(__name__)


class QuoteNotFoundError(Exception):
    """No quote matches the given reference within this organization."""


class CustomerNotFoundInOrgError(Exception):
    """customer_id doesn't reference a customer in this organization."""


class ProductNotFoundInOrgError(Exception):
    """A line item's product_id doesn't reference a product in this
    organization."""


class ExpiryDateBeforeIssueDateError(Exception):
    """The requested expiry_date is before the organization's local today
    at creation time."""


class QuoteNotDraftError(Exception):
    """The requested operation (hard delete) only applies to draft quotes."""


class QuoteAlreadyRespondedError(Exception):
    """The quote is not currently "sent" -- accept/reject only applies to
    a quote the customer hasn't already decided on (or that hasn't expired
    /been converted)."""


class QuoteNotAcceptedError(Exception):
    """Conversion to an invoice is gated to status == accepted only (see
    the plan's locked decision) -- draft/sent/rejected/expired quotes
    cannot be converted."""


class QuoteAlreadyConvertedError(Exception):
    """converted_invoice_id is already set -- a quote can never be
    converted twice."""


class CustomerEmailMissingError(Exception):
    """The quote's customer has no email on file."""


class EmailSendFailedError(Exception):
    """The configured email provider failed to send. Wraps the original
    EmailSendError so callers never need to import app.email.base
    directly."""


class QuoteReminderAlreadySentError(Exception):
    """The unique constraint on (quote_id, scheduled_for_date) already has
    a row -- this exact reminder slot was already claimed. Mirrors
    ReminderAlreadySentError in app.services.invoices exactly."""


class QuoteNotEligibleForReminderError(Exception):
    """The quote's effective status is no longer "sent" (accepted,
    rejected, expired, or converted in the interim) -- re-checked fresh
    immediately after the claim succeeds, exactly like
    claim_and_send_reminder re-checks payment_status/due_date."""


class QuoteReminderSendFailedError(Exception):
    """The configured email provider failed to send this reminder. Wraps
    the original EmailSendError so callers never need to import
    app.email.base directly."""


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


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


def _validate_line_item_products(
    db: Session, organization_id: str, line_items: list[QuoteLineItemCreate]
) -> dict[str, Product]:
    """A line's product_id is purely an analytics tag (see
    QuoteLineItem.product_id's docstring) -- validated to resolve within
    this organization here, but description/quantity/unit_price always
    come from `line_items` as given, never re-derived from the live
    product row. Returns the resolved Product rows keyed by id so callers
    can feed them into resolve_document_currency_code with no extra
    queries."""
    resolved_products_by_id: dict[str, Product] = {}
    for line in line_items:
        if line.product_id is not None:
            try:
                resolved_products_by_id[line.product_id] = get_product_in_org(
                    db, organization_id, line.product_id
                )
            except ProductNotFoundError:
                raise ProductNotFoundInOrgError(line.product_id)
    return resolved_products_by_id


def create_quote_record(
    db: Session,
    organization_id: str,
    current_user: User,
    customer: Customer | None,
    currency_code: CurrencyCode | None,
    line_items: list[QuoteLineItemCreate],
    tax_rate: Decimal,
    expiry_date: date | None = None,
    notes: str = "",
) -> Quote:
    """The actual DB write: numbering-locked, currency/language pinned at
    creation time, exactly mirroring create_invoice_record. Totals are
    always recomputed here from `line_items` -- never accepted as a
    parameter."""
    resolved_products_by_id = _validate_line_item_products(db, organization_id, line_items)

    # compute_invoice_totals is a pure function of any object exposing
    # .quantity/.unit_price -- QuoteLineItemCreate has the identical shape
    # to InvoiceLineItemCreate, so this is reused completely unchanged.
    totals = compute_invoice_totals(line_items, tax_rate)  # type: ignore[arg-type]
    line_models = [
        QuoteLineItem(
            description=line.description,
            quantity=line.quantity,
            unit_price=_quantize_money(line.unit_price),
            line_total=line_total,
            product_id=line.product_id,
        )
        for line, line_total in zip(line_items, totals.line_totals)
    ]

    organization = db.execute(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    ).scalar_one()

    today_local = get_organization_today(organization)
    if expiry_date is not None and expiry_date < today_local:
        raise ExpiryDateBeforeIssueDateError(expiry_date)

    quote_number = organization.next_quote_number
    organization.next_quote_number = quote_number + 1

    resolved_currency_code = resolve_document_currency_code(
        currency_code.value if currency_code else None,
        line_items,
        resolved_products_by_id,
    )
    language = organization.language

    quote = Quote(
        organization_id=organization_id,
        quote_number=quote_number,
        created_by_user_id=current_user.id,
        customer_id=customer.id if customer else None,
        subtotal=totals.subtotal,
        tax_rate=tax_rate,
        tax_amount=totals.tax_amount,
        total=totals.total,
        currency_code=resolved_currency_code,
        language=language,
        issue_date=today_local,
        expiry_date=expiry_date,
        notes=notes,
        public_token=generate_quote_public_token(),
        line_items=line_models,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return quote


def get_quote_in_org(db: Session, organization_id: str, quote_reference: str) -> Quote:
    """Resolves a quote scoped to organization_id, by raw id OR a human
    quote reference ("QUO-000023", "23", "000023") -- mirrors
    get_invoice_in_org exactly."""
    parsed_number = parse_quote_number(quote_reference)
    if parsed_number is not None:
        quote = db.scalar(
            select(Quote).where(
                Quote.organization_id == organization_id,
                Quote.quote_number == parsed_number,
            )
        )
        if quote is not None:
            return quote

    quote = db.scalar(
        select(Quote).where(
            Quote.id == quote_reference,
            Quote.organization_id == organization_id,
        )
    )
    if quote is None:
        raise QuoteNotFoundError(quote_reference)
    return quote


def get_quote_by_public_token(db: Session, raw_token: str) -> Quote:
    quote = db.scalar(select(Quote).where(Quote.public_token == raw_token))
    if quote is None:
        raise QuoteNotFoundError(raw_token)
    return quote


# Sentinel distinguishing "field not given" from "field explicitly set to
# None" for customer_id/expiry_date, both of which are legitimately
# nullable -- mirrors the same need OrganizationUpdateRequest's
# exclude_unset handles at the schema layer, just at the service layer
# instead since this function takes already-resolved values, not a request
# body.
_UNSET: Any = object()


def update_quote_record(
    db: Session,
    organization_id: str,
    quote: Quote,
    customer: Customer | None = _UNSET,
    line_items: list[QuoteLineItemCreate] | None = None,
    tax_rate: Decimal | None = None,
    expiry_date: date | None = _UNSET,
    notes: str | None = None,
) -> Quote:
    """Partial update -- only fields explicitly given are changed. Totals
    are always fully recomputed from the resulting line_items/tax_rate,
    never patched incrementally, so subtotal/tax_amount/total can never
    drift from what the stored line items actually add up to."""
    if customer is not _UNSET:
        quote.customer_id = customer.id if customer else None
    if expiry_date is not _UNSET:
        today_local = get_organization_today(quote.organization)
        if expiry_date is not None and expiry_date < today_local:
            raise ExpiryDateBeforeIssueDateError(expiry_date)
        quote.expiry_date = expiry_date
    if notes is not None:
        quote.notes = notes

    effective_tax_rate = tax_rate if tax_rate is not None else quote.tax_rate

    if line_items is not None:
        resolved_products_by_id = _validate_line_item_products(db, organization_id, line_items)
        # The quote's currency is already pinned and immutable post-creation
        # (see QuoteUpdateRequest -- it has no currency_code field), so this
        # reduces to "every replacement product-linked line must match it."
        resolve_document_currency_code(quote.currency_code, line_items, resolved_products_by_id)
        totals = compute_invoice_totals(line_items, effective_tax_rate)  # type: ignore[arg-type]
        quote.line_items = [
            QuoteLineItem(
                description=line.description,
                quantity=line.quantity,
                unit_price=_quantize_money(line.unit_price),
                line_total=line_total,
                product_id=line.product_id,
            )
            for line, line_total in zip(line_items, totals.line_totals)
        ]
        quote.subtotal = totals.subtotal
        quote.tax_rate = effective_tax_rate
        quote.tax_amount = totals.tax_amount
        quote.total = totals.total
    elif tax_rate is not None:
        existing_line_items = [
            QuoteLineItemCreate(
                description=li.description,
                quantity=li.quantity,
                unit_price=li.unit_price,
                product_id=li.product_id,
            )
            for li in quote.line_items
        ]
        totals = compute_invoice_totals(existing_line_items, effective_tax_rate)  # type: ignore[arg-type]
        quote.subtotal = totals.subtotal
        quote.tax_rate = effective_tax_rate
        quote.tax_amount = totals.tax_amount
        quote.total = totals.total

    db.commit()
    db.refresh(quote)
    return quote


def archive_quote_record(db: Session, quote: Quote) -> Quote:
    """Idempotent -- mirrors archive_product_record exactly."""
    if quote.active:
        quote.active = False
        db.commit()
        db.refresh(quote)
    return quote


def restore_quote_record(db: Session, quote: Quote) -> Quote:
    if not quote.active:
        quote.active = True
        db.commit()
        db.refresh(quote)
    return quote


def delete_draft_quote_record(db: Session, quote: Quote) -> None:
    """Hard delete -- only ever legal for status == draft (see
    QuoteNotDraftError). Anything sent/accepted/rejected/expired/converted
    can only ever be archived, never deleted -- it may already be
    customer-facing history."""
    if quote.status != QuoteStatus.draft.value:
        raise QuoteNotDraftError(quote.id)
    db.delete(quote)
    db.commit()


def duplicate_quote_record(
    db: Session, organization_id: str, current_user: User, quote: Quote
) -> Quote:
    """Copies customer/line items/tax/notes/currency into a brand-new
    draft quote with a fresh quote_number and no converted_invoice_id --
    quote-lifecycle logic, not totals math, so it lives here rather than
    in app.services.invoices."""
    line_items = [
        QuoteLineItemCreate(
            description=li.description,
            quantity=li.quantity,
            unit_price=li.unit_price,
            product_id=li.product_id,
        )
        for li in quote.line_items
    ]
    return create_quote_record(
        db,
        organization_id,
        current_user,
        quote.customer,
        CurrencyCode(quote.currency_code),
        line_items,
        quote.tax_rate,
        expiry_date=None,
        notes=quote.notes,
    )


def _require_sent(quote: Quote) -> None:
    today_local = get_organization_today(quote.organization)
    if get_effective_quote_status(quote, today_local) != QuoteStatus.sent:
        raise QuoteAlreadyRespondedError(quote.id)


def mark_quote_accepted_record(db: Session, quote: Quote) -> Quote:
    """Shared by the public accept endpoint and the authenticated "Mark as
    accepted" action -- only legal from effective_status == sent."""
    _require_sent(quote)
    quote.status = QuoteStatus.accepted.value
    db.commit()
    db.refresh(quote)
    return quote


def mark_quote_rejected_record(db: Session, quote: Quote) -> Quote:
    _require_sent(quote)
    quote.status = QuoteStatus.rejected.value
    db.commit()
    db.refresh(quote)
    return quote


@dataclass
class QuoteConversionResult:
    invoice: Invoice


def convert_quote_to_invoice(
    db: Session, organization_id: str, quote: Quote, current_user: User
) -> QuoteConversionResult:
    """Creates a brand-new, fully independent invoice from an accepted
    quote by calling create_invoice_record (from app.services.invoices)
    completely unchanged -- zero duplicated totals/tax/numbering logic.
    The resulting invoice has fresh InvoiceLineItem rows (new ids) and
    never references the quote; only the quote gains a one-directional
    converted_invoice_id pointer back to it."""
    if quote.converted_invoice_id is not None:
        raise QuoteAlreadyConvertedError(quote.id)
    if quote.status != QuoteStatus.accepted.value:
        raise QuoteNotAcceptedError(quote.id)

    invoice_line_items = [
        InvoiceLineItemCreate(
            description=li.description,
            quantity=li.quantity,
            unit_price=li.unit_price,
            product_id=li.product_id,
        )
        for li in quote.line_items
    ]

    invoice = create_invoice_record(
        db,
        organization_id,
        current_user,
        quote.customer,
        CurrencyCode(quote.currency_code),
        invoice_line_items,
        quote.tax_rate,
    )

    quote.status = QuoteStatus.converted.value
    quote.converted_invoice_id = invoice.id
    db.commit()
    db.refresh(quote)
    db.refresh(invoice)
    return QuoteConversionResult(invoice=invoice)


def send_quote_record(db: Session, quote: Quote) -> SendQuoteEmailResponse:
    customer = quote.customer
    if customer is None or not customer.email:
        raise CustomerEmailMissingError(quote.id)

    email_sender = get_email_sender()
    pdf_bytes = render_quote_pdf(quote)
    filename = f"{format_quote_number(quote.quote_number)}.pdf"
    accept_link = f"{build_quote_public_link(quote.public_token)}/accept"
    reject_link = f"{build_quote_public_link(quote.public_token)}/reject"
    subject, body = build_quote_email(quote, customer, accept_link, reject_link)

    message = EmailMessage(
        to=customer.email,
        subject=subject,
        text_body=body,
        attachments=[EmailAttachment(filename=filename, content=pdf_bytes)],
    )

    logger.info(
        "send_quote_record: sending quote email organization_id=%s quote_id=%s",
        quote.organization_id,
        quote.id,
    )

    try:
        email_sender.send(message)
    except EmailSendError as exc:
        logger.error(
            "send_quote_record: failed to send quote email "
            "organization_id=%s quote_id=%s exception_type=%s exception_message=%s",
            quote.organization_id,
            quote.id,
            type(exc).__name__,
            str(exc),
        )
        raise EmailSendFailedError(quote.id) from exc

    # Only flips draft -> sent once the email has actually been delivered
    # -- a failed send must never leave the quote silently eligible for
    # accept/reject on a public link the customer never received. Re-
    # sending an already-sent quote is a harmless no-op status-wise.
    if quote.status == QuoteStatus.draft.value:
        quote.status = QuoteStatus.sent.value
        db.commit()
        db.refresh(quote)

    logger.info(
        "send_quote_record: quote email sent successfully organization_id=%s quote_id=%s",
        quote.organization_id,
        quote.id,
    )
    return SendQuoteEmailResponse(sent=True, sent_to=customer.email)


def claim_and_send_quote_reminder(
    db: Session,
    organization: Organization,
    quote: Quote,
    days_offset: int,
    scheduled_for_date: date,
    triggered_by: str,
) -> None:
    """Claim -> re-validate -> send -> update. Mirrors
    app.services.invoices.claim_and_send_reminder's exact sequence and
    rationale: the INSERT below (unique on quote_id + scheduled_for_date)
    is the entire concurrency/idempotency guarantee, portable across
    SQLite and Postgres with no dialect-specific SQL. Eligibility (still
    effectively "sent", has an expiry date, customer has an email) is
    re-checked fresh immediately after the claim succeeds -- never trusted
    from an earlier lookup -- so a quote accepted/rejected a moment before
    this runs is always respected.
    """
    customer = quote.customer
    if customer is None or not customer.email:
        raise CustomerEmailMissingError(quote.id)

    reminder = QuoteReminder(
        organization_id=organization.id,
        quote_id=quote.id,
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
        raise QuoteReminderAlreadySentError(quote.id)
    db.refresh(reminder)

    db.refresh(quote)
    today_local = get_organization_today(organization)
    if get_effective_quote_status(quote, today_local) != QuoteStatus.sent:
        reminder.status = ReminderStatus.skipped.value
        reminder.failure_code = "quote_not_eligible"
        db.commit()
        raise QuoteNotEligibleForReminderError(quote.id)

    if quote.expiry_date is None:
        reminder.status = ReminderStatus.skipped.value
        reminder.failure_code = "quote_expiry_date_missing"
        db.commit()
        raise QuoteNotEligibleForReminderError(quote.id)

    days_until_expiry = (quote.expiry_date - today_local).days
    subject, body = build_quote_reminder_email(quote, customer, days_until_expiry)

    email_sender = get_email_sender()
    pdf_bytes = render_quote_pdf(quote)
    filename = f"{format_quote_number(quote.quote_number)}.pdf"
    message = EmailMessage(
        to=customer.email,
        subject=subject,
        text_body=body,
        attachments=[EmailAttachment(filename=filename, content=pdf_bytes)],
    )

    logger.info(
        "claim_and_send_quote_reminder: sending organization_id=%s quote_id=%s triggered_by=%s",
        organization.id,
        quote.id,
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
            "claim_and_send_quote_reminder: failed to send organization_id=%s quote_id=%s "
            "exception_type=%s exception_message=%s",
            organization.id,
            quote.id,
            type(exc).__name__,
            str(exc),
        )
        raise QuoteReminderSendFailedError(quote.id) from exc

    reminder.status = ReminderStatus.sent.value
    reminder.sent_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        "claim_and_send_quote_reminder: sent successfully organization_id=%s quote_id=%s",
        organization.id,
        quote.id,
    )
