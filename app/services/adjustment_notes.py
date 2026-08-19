"""Credit and debit notes (Phase 29) -- the one place note arithmetic
lives.

Every derived figure in the application that has to account for
adjustments (the invoice API, receivables, revenue analytics, the
forecasting series, the AI Advisor's deterministic context) calls into
this module rather than re-summing notes itself. That is deliberate: note
arithmetic has a sign, a status filter and a currency rule, and three
copies of it would eventually disagree.

THE FOUR RULES EVERYTHING ELSE FOLLOWS

1.  Invoice.total is never mutated. It stays the historical record of
    what was issued. Adjusted values are computed, never stored.
2.  Only `issued` notes count. Draft and void are economically inert
    everywhere -- see AdjustmentNoteStatus.affects_invoice_economics,
    which is the single predicate.
3.  Notes are never negative invoices. Lines carry positive amounts; the
    direction comes from note_type, applied exactly once by
    signed_total().
4.  The source invoice is the authority for organization, customer and
    currency. None of those is ever accepted from a caller.

Raises small typed exceptions rather than HTTPException, matching
app.services.invoices' own contract, so routers and (future) tools can
translate them independently.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adjustment_note_status import AdjustmentNoteStatus
from app.adjustment_note_type import AdjustmentNoteType
from app.models import (
    AdjustmentNote,
    AdjustmentNoteLineItem,
    Invoice,
    InvoiceLineItem,
    Organization,
    User,
)
from app.notifications.service import emit_event
from app.org_time import get_organization_today
from app.services.invoices import compute_invoice_totals
from app.tax_groups import MONEY_EXPONENT
from app.webhook_event_type import WebhookEventType

logger = logging.getLogger(__name__)


# --- errors -----------------------------------------------------------


class AdjustmentNoteNotFoundError(Exception):
    """No note matches the given id within this organization."""


class SourceInvoiceNotFoundError(Exception):
    """source_invoice_id doesn't reference an invoice in this
    organization. Deliberately indistinguishable from "does not exist":
    a caller must never be able to probe another tenant's invoice ids."""


class NoteNotDraftError(Exception):
    """The operation requires a draft note. An issued note's financial
    fields are immutable -- correcting one means voiding it and issuing
    another, never editing history in place."""


class NoteNotIssuedError(Exception):
    """The operation requires an issued note (e.g. voiding one)."""


class NoteAlreadyVoidError(Exception):
    """Voiding is terminal; a void note is never reopened."""


class EmptyNoteError(Exception):
    """A note with no lines has no economic meaning."""


class OverCreditError(Exception):
    """The requested credit exceeds what remains creditable against the
    source invoice as a whole."""

    def __init__(self, requested: Decimal, remaining: Decimal, currency_code: str) -> None:
        super().__init__(f"requested {requested} exceeds remaining creditable {remaining}")
        self.requested = requested
        self.remaining = remaining
        self.currency_code = currency_code

    def to_error_detail(self) -> dict:
        return {
            "code": "over_credit",
            "message": "This credit note exceeds the amount still creditable on the invoice.",
            "requested": str(self.requested),
            "remaining_creditable": str(self.remaining),
            "currency_code": self.currency_code,
        }


class LineOverCreditError(Exception):
    """A single line credits more of a source invoice line than remains.

    Distinct from OverCreditError on purpose: a note can be within the
    document-level ceiling while still crediting one line twice over, and
    the user needs to be told which line.
    """

    def __init__(
        self, source_line_id: str, description: str, requested: Decimal, remaining: Decimal
    ) -> None:
        super().__init__(f"line {source_line_id}: requested {requested}, remaining {remaining}")
        self.source_line_id = source_line_id
        self.description = description
        self.requested = requested
        self.remaining = remaining

    def to_error_detail(self) -> dict:
        return {
            "code": "line_over_credit",
            "message": "One line credits more than remains creditable on that invoice line.",
            "source_invoice_line_item_id": self.source_line_id,
            "description": self.description,
            "requested": str(self.requested),
            "remaining_creditable": str(self.remaining),
        }


class SourceLineNotOnInvoiceError(Exception):
    """A line references an invoice line that doesn't belong to the source
    invoice -- the cross-document equivalent of a cross-tenant reference,
    and blocked for the same reason."""


class DebitLineCannotReferenceSourceError(Exception):
    """Debit-note lines are free-form by design (see
    docs/credit_debit_notes.md): a debit note adds a charge that was NOT
    on the invoice, so there is nothing for a source-line reference to
    constrain, and allowing one would create a second, contradictory
    meaning for source_invoice_line_item_id."""


# --- value objects ----------------------------------------------------


@dataclass(frozen=True)
class InvoiceAdjustments:
    """Everything derived about one invoice's adjustments, computed once.

    All amounts are in the invoice's own currency -- a note can never have
    a different one, so no cross-currency arithmetic is possible here by
    construction.
    """

    original_total: Decimal
    credited_total: Decimal
    debited_total: Decimal
    adjusted_total: Decimal
    remaining_creditable: Decimal
    currency_code: str
    issued_credit_note_count: int
    issued_debit_note_count: int

    @property
    def has_adjustments(self) -> bool:
        return bool(self.issued_credit_note_count or self.issued_debit_note_count)


def signed_total(note_type: AdjustmentNoteType | str, total: Decimal) -> Decimal:
    """The ONE place a note's economic direction is applied.

    Credit notes reduce, debit notes increase. Everything upstream stores
    and displays positive amounts; nothing else in the codebase should
    ever write `-total`.
    """
    resolved = AdjustmentNoteType(note_type)
    return -Decimal(total) if resolved is AdjustmentNoteType.credit else Decimal(total)


# --- reading adjustments ----------------------------------------------


def get_invoice_adjustments(db: Session, invoice: Invoice) -> InvoiceAdjustments:
    """The authoritative adjusted view of one invoice.

    REMAINING CREDITABLE = original_total - issued credits.

    Debit notes deliberately do NOT raise the ceiling. A debit note adds a
    NEW charge; letting it expand how much of the ORIGINAL sale can be
    reversed would allow a round trip (debit +500, then credit -500
    against the original) that nets to zero economically while quietly
    increasing total reversibility. The conservative reading keeps
    "how much of this sale can still be undone" tied to the sale itself.
    Documented in docs/credit_debit_notes.md.
    """
    rows = db.execute(
        select(
            AdjustmentNote.note_type,
            func.coalesce(func.sum(AdjustmentNote.total), 0),
            func.count(AdjustmentNote.id),
        )
        .where(
            AdjustmentNote.source_invoice_id == invoice.id,
            AdjustmentNote.status == AdjustmentNoteStatus.issued.value,
        )
        .group_by(AdjustmentNote.note_type)
    ).all()

    credited = Decimal("0")
    debited = Decimal("0")
    credit_count = 0
    debit_count = 0
    for note_type, total, count in rows:
        if AdjustmentNoteType(note_type) is AdjustmentNoteType.credit:
            credited, credit_count = Decimal(str(total)), count
        else:
            debited, debit_count = Decimal(str(total)), count

    original = Decimal(invoice.total)
    return InvoiceAdjustments(
        original_total=original,
        credited_total=credited.quantize(MONEY_EXPONENT),
        debited_total=debited.quantize(MONEY_EXPONENT),
        adjusted_total=(original - credited + debited).quantize(MONEY_EXPONENT),
        remaining_creditable=max(Decimal("0"), original - credited).quantize(MONEY_EXPONENT),
        currency_code=invoice.currency_code,
        issued_credit_note_count=credit_count,
        issued_debit_note_count=debit_count,
    )


def get_adjusted_totals_by_invoice(
    db: Session, organization_id: str, invoice_ids: list[str] | None = None
) -> dict[str, Decimal]:
    """Net signed adjustment per invoice, as ONE bounded query.

    This is what analytics and receivables use: never a per-invoice call
    in a loop, and never their own note arithmetic. Invoices with no
    issued notes are simply absent from the result, so callers apply
    `.get(invoice_id, 0)` and pay nothing for the common case.
    """
    query = (
        select(
            AdjustmentNote.source_invoice_id,
            AdjustmentNote.note_type,
            func.coalesce(func.sum(AdjustmentNote.total), 0),
        )
        .where(
            AdjustmentNote.organization_id == organization_id,
            AdjustmentNote.status == AdjustmentNoteStatus.issued.value,
        )
        .group_by(AdjustmentNote.source_invoice_id, AdjustmentNote.note_type)
    )
    if invoice_ids is not None:
        if not invoice_ids:
            return {}
        query = query.where(AdjustmentNote.source_invoice_id.in_(invoice_ids))

    adjustments: dict[str, Decimal] = {}
    for invoice_id, note_type, total in db.execute(query).all():
        adjustments[invoice_id] = adjustments.get(invoice_id, Decimal("0")) + signed_total(
            note_type, Decimal(str(total))
        )
    return {k: v.quantize(MONEY_EXPONENT) for k, v in adjustments.items()}


def get_line_credit_usage(db: Session, invoice_id: str) -> dict[str, Decimal]:
    """How much of each invoice LINE has already been credited, by value.

    Value rather than quantity, deliberately: a partial credit may be a
    post-hoc discount on the same quantity ("credit 100 off these 10
    units") rather than a return, and value is the only measure that
    covers both without inventing a second unit system. Quantity remains
    visible on the note line for the reader.

    Counts issued notes only, matching every other derived figure here.
    """
    rows = db.execute(
        select(
            AdjustmentNoteLineItem.source_invoice_line_item_id,
            func.coalesce(func.sum(AdjustmentNoteLineItem.line_total), 0),
        )
        .join(AdjustmentNote, AdjustmentNote.id == AdjustmentNoteLineItem.note_id)
        .where(
            AdjustmentNote.source_invoice_id == invoice_id,
            AdjustmentNote.status == AdjustmentNoteStatus.issued.value,
            AdjustmentNote.note_type == AdjustmentNoteType.credit.value,
            AdjustmentNoteLineItem.source_invoice_line_item_id.is_not(None),
        )
        .group_by(AdjustmentNoteLineItem.source_invoice_line_item_id)
    ).all()
    return {line_id: Decimal(str(used)).quantize(MONEY_EXPONENT) for line_id, used in rows}


def get_creditable_lines(db: Session, invoice: Invoice) -> list[dict]:
    """Per-line remaining creditable value for the source invoice -- what
    a "create credit note" screen needs to prefill itself and to show the
    user what is still available."""
    used = get_line_credit_usage(db, invoice.id)
    lines = []
    for item in invoice.line_items:
        already = used.get(item.id, Decimal("0"))
        lines.append(
            {
                "invoice_line_item_id": item.id,
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
                "tax_rate": item.tax_rate,
                "credited_total": already,
                "remaining_creditable": max(
                    Decimal("0"), Decimal(item.line_total) - already
                ).quantize(MONEY_EXPONENT),
            }
        )
    return lines


# --- writing ----------------------------------------------------------


def get_note_in_org(db: Session, organization_id: str, note_id: str) -> AdjustmentNote:
    note = db.scalar(
        select(AdjustmentNote).where(
            AdjustmentNote.id == note_id,
            AdjustmentNote.organization_id == organization_id,
        )
    )
    if note is None:
        raise AdjustmentNoteNotFoundError(note_id)
    return note


def _get_source_invoice_locked(db: Session, organization_id: str, source_invoice_id: str) -> Invoice:
    """Fetches the source invoice WITH A ROW LOCK.

    This is the concurrency boundary for over-credit protection. Two
    simultaneous credit notes against the same invoice serialize here, so
    the second one reads the first one's committed effect before
    computing what remains -- rather than both reading the same stale
    remaining balance and both passing an application-level pre-check.

    A real lock on PostgreSQL; a no-op on SQLite, which serializes
    writers itself. Same pattern the invoice numbering already uses.
    """
    invoice = db.execute(
        select(Invoice)
        .where(Invoice.id == source_invoice_id, Invoice.organization_id == organization_id)
        .with_for_update()
    ).scalar_one_or_none()
    if invoice is None:
        raise SourceInvoiceNotFoundError(source_invoice_id)
    return invoice


def _allocate_note_number(db: Session, organization_id: str, note_type: AdjustmentNoteType) -> int:
    """Consumes one number from this organization's per-type sequence,
    under the same organization-row lock that hands out invoice numbers,
    so concurrent creations can never receive the same number."""
    organization = db.execute(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    ).scalar_one()
    if note_type is AdjustmentNoteType.credit:
        number = organization.next_credit_note_number
        organization.next_credit_note_number = number + 1
    else:
        number = organization.next_debit_note_number
        organization.next_debit_note_number = number + 1
    return number


def create_adjustment_note(
    db: Session,
    organization_id: str,
    *,
    note_type: AdjustmentNoteType,
    source_invoice_id: str,
    line_items: list,
    reason: str = "",
    current_user: User | None = None,
    issue_immediately: bool = False,
) -> AdjustmentNote:
    """Creates a credit or debit note against an existing invoice.

    `line_items` are request objects exposing description / quantity /
    unit_price / tax_rate / source_invoice_line_item_id. Totals are
    always recomputed here from those lines via Phase 28's
    compute_invoice_totals -- never accepted from the caller -- so
    nothing upstream can hand this function a pre-computed total to
    trust.

    organization_id / customer / currency are taken from the SOURCE
    INVOICE, never from the request. That is what makes a cross-tenant or
    mismatched-currency note impossible rather than merely rejected.
    """
    if not line_items:
        raise EmptyNoteError("a note needs at least one line")

    invoice = _get_source_invoice_locked(db, organization_id, source_invoice_id)

    resolved_lines = _resolve_lines(db, invoice, note_type, line_items)

    # Phase 28's calculation, unchanged: per-line rates, grouped by rate,
    # quantized once per group. Notes get identical tax behavior to
    # invoices and quotes because they run the identical function.
    totals = compute_invoice_totals(resolved_lines, Decimal("0"))

    if note_type is AdjustmentNoteType.credit:
        _assert_within_credit_ceiling(db, invoice, totals.total)
        _assert_within_line_ceilings(db, invoice, resolved_lines)

    number = _allocate_note_number(db, organization_id, note_type)

    note = AdjustmentNote(
        organization_id=organization_id,
        source_invoice_id=invoice.id,
        customer_id=invoice.customer_id,
        created_by_user_id=current_user.id if current_user is not None else None,
        note_type=note_type.value,
        note_number=number,
        status=AdjustmentNoteStatus.draft.value,
        reason=reason,
        subtotal=totals.subtotal,
        tax_amount=totals.tax_amount,
        total=totals.total,
        currency_code=invoice.currency_code,
        language=invoice.language,
        # Forwarded from the INVOICE's own snapshot, not from the live
        # customer row -- same rule convert_quote_to_invoice follows, so
        # a customer edited since the invoice was issued cannot change
        # what the note says.
        customer_name_snapshot=invoice.customer_name_snapshot,
        customer_email_snapshot=invoice.customer_email_snapshot,
        customer_phone_snapshot=invoice.customer_phone_snapshot,
        customer_address_snapshot=invoice.customer_address_snapshot,
    )
    note.line_items = [
        AdjustmentNoteLineItem(
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            line_total=line_total,
            tax_rate=line.tax_rate,
            source_invoice_line_item_id=line.source_invoice_line_item_id,
        )
        for line, line_total in zip(resolved_lines, totals.line_totals)
    ]
    db.add(note)
    db.flush()

    _emit(db, note, WebhookEventType.adjustment_note_created, current_user)

    if issue_immediately:
        # Same transaction, so a note created-and-issued in one call can
        # never be left half-way if issuing fails.
        issue_adjustment_note(db, note, current_user=current_user, commit=False)

    db.commit()
    db.refresh(note)
    return note


@dataclass(frozen=True)
class _ResolvedLine:
    """A note line after its snapshot fields have been settled from the
    source invoice line (when there is one). Shaped to satisfy
    compute_invoice_totals, which only reads quantity/unit_price/tax_rate."""

    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    source_invoice_line_item_id: str | None


def _resolve_lines(
    db: Session, invoice: Invoice, note_type: AdjustmentNoteType, line_items: list
) -> list[_ResolvedLine]:
    """Settles each line's historical snapshot values.

    When a credit line references an invoice line, description and
    tax_rate are copied FROM THAT LINE unless the caller supplied their
    own -- never from the Product's current configuration. This is the
    Phase 28 snapshot rule applied one document further along: changing
    Product.default_tax_rate after the fact must not move an invoice, and
    must equally not move a note that credits it.
    """
    invoice_lines = {item.id: item for item in invoice.line_items}
    resolved: list[_ResolvedLine] = []

    for line in line_items:
        source_id = getattr(line, "source_invoice_line_item_id", None)

        if source_id is not None:
            if note_type is AdjustmentNoteType.debit:
                raise DebitLineCannotReferenceSourceError(source_id)
            source = invoice_lines.get(source_id)
            if source is None:
                raise SourceLineNotOnInvoiceError(source_id)
            description = line.description or source.description
            unit_price = line.unit_price if line.unit_price is not None else source.unit_price
            tax_rate = line.tax_rate if line.tax_rate is not None else source.tax_rate
        else:
            source = None
            description = line.description
            unit_price = line.unit_price
            # A free-form line with no rate supplied is exempt rather than
            # inheriting anything: there is no source line to inherit
            # from, and silently guessing a rate on a financial document
            # would be worse than requiring the caller to say.
            tax_rate = line.tax_rate if line.tax_rate is not None else Decimal("0")

        resolved.append(
            _ResolvedLine(
                description=description,
                quantity=Decimal(line.quantity),
                unit_price=Decimal(unit_price),
                tax_rate=Decimal(tax_rate),
                source_invoice_line_item_id=source_id,
            )
        )
    return resolved


def _assert_within_credit_ceiling(db: Session, invoice: Invoice, requested: Decimal) -> None:
    """Document-level over-credit protection.

    Runs INSIDE the transaction that holds the source invoice's row lock
    (see _get_source_invoice_locked), which is what makes it a real
    guarantee rather than a pre-check that two concurrent requests can
    both pass.
    """
    adjustments = get_invoice_adjustments(db, invoice)
    if requested > adjustments.remaining_creditable:
        raise OverCreditError(
            requested=requested,
            remaining=adjustments.remaining_creditable,
            currency_code=invoice.currency_code,
        )


def _assert_within_line_ceilings(
    db: Session, invoice: Invoice, resolved_lines: list[_ResolvedLine]
) -> None:
    """Line-level over-credit protection.

    A note can sit inside the document ceiling while still crediting one
    invoice line twice over -- e.g. crediting line A's full value twice
    on a two-line invoice. Checking only the total would let that through,
    so each referenced line is checked against its own remaining value,
    including other lines in THIS same note.
    """
    used = get_line_credit_usage(db, invoice.id)
    invoice_lines = {item.id: item for item in invoice.line_items}
    requested_here: dict[str, Decimal] = {}

    for line in resolved_lines:
        source_id = line.source_invoice_line_item_id
        if source_id is None:
            continue
        amount = (line.quantity * line.unit_price).quantize(MONEY_EXPONENT)
        requested_here[source_id] = requested_here.get(source_id, Decimal("0")) + amount

    for source_id, requested in requested_here.items():
        source = invoice_lines[source_id]
        remaining = max(
            Decimal("0"), Decimal(source.line_total) - used.get(source_id, Decimal("0"))
        ).quantize(MONEY_EXPONENT)
        if requested > remaining:
            raise LineOverCreditError(
                source_line_id=source_id,
                description=source.description,
                requested=requested,
                remaining=remaining,
            )


def issue_adjustment_note(
    db: Session,
    note: AdjustmentNote,
    *,
    current_user: User | None = None,
    commit: bool = True,
) -> AdjustmentNote:
    """draft -> issued. The note becomes financially immutable and starts
    counting toward every derived figure.

    The credit ceiling is re-checked here, not only at creation: a note
    may have sat in draft while other notes were issued against the same
    invoice, and the ceiling that mattered at creation time may no longer
    hold. Runs under the same source-invoice row lock.
    """
    if note.status != AdjustmentNoteStatus.draft.value:
        raise NoteNotDraftError(note.id)

    invoice = _get_source_invoice_locked(db, note.organization_id, note.source_invoice_id)
    if AdjustmentNoteType(note.note_type) is AdjustmentNoteType.credit:
        _assert_within_credit_ceiling(db, invoice, Decimal(note.total))

    note.status = AdjustmentNoteStatus.issued.value
    note.issued_at = datetime.now(timezone.utc)
    if note.issue_date is None:
        note.issue_date = get_organization_today(invoice.organization)

    _emit(db, note, WebhookEventType.adjustment_note_issued, current_user)
    if commit:
        db.commit()
        db.refresh(note)
    return note


def void_adjustment_note(
    db: Session, note: AdjustmentNote, *, current_user: User | None = None
) -> AdjustmentNote:
    """issued -> void. The note is retained forever and stays visible in
    history and audit, but stops affecting any derived figure -- which
    also frees up the credit ceiling it was consuming.

    Never deletes. Financial history is not erased in this application.
    """
    if note.status == AdjustmentNoteStatus.void.value:
        raise NoteAlreadyVoidError(note.id)
    if note.status != AdjustmentNoteStatus.issued.value:
        raise NoteNotIssuedError(note.id)

    note.status = AdjustmentNoteStatus.void.value
    note.voided_at = datetime.now(timezone.utc)

    _emit(db, note, WebhookEventType.adjustment_note_voided, current_user)
    db.commit()
    db.refresh(note)
    return note


def delete_draft_note(
    db: Session, note: AdjustmentNote, *, current_user: User | None = None
) -> None:
    """Draft notes may be discarded outright -- they never affected any
    figure and carry no financial history. An issued note can only ever
    be voided."""
    if note.status != AdjustmentNoteStatus.draft.value:
        raise NoteNotDraftError(note.id)
    db.delete(note)
    db.commit()


def _emit(
    db: Session, note: AdjustmentNote, event_type: WebhookEventType, actor: User | None
) -> None:
    """One canonical fan-out path, exactly like every other domain event
    in this codebase -- audit, notification, webhook and email all follow
    from this single call, never from separate ones.

    The payload is deliberately PII-minimal: ids, type, number, status,
    currency and amounts. `reason` is free text a user typed and is NOT
    included, matching the same restraint applied to the AI context.
    """
    emit_event(
        db,
        organization_id=note.organization_id,
        event_type=event_type,
        object_type="adjustment_note",
        object_id=note.id,
        payload={
            "note_id": note.id,
            "note_type": note.note_type,
            "note_number": note.formatted_number,
            "source_invoice_id": note.source_invoice_id,
            "organization_id": note.organization_id,
            "status": note.status,
            "currency_code": note.currency_code,
            "subtotal": str(note.subtotal),
            "tax_amount": str(note.tax_amount),
            "total": str(note.total),
        },
        actor_user_id=actor.id if actor is not None else None,
    )


class NoteNotSendableError(Exception):
    """Only an ISSUED note may be emailed.

    A draft is not a document the customer should ever see -- it has no
    issue date, it is still editable, and it counts toward nothing. This
    matches the quote convention (a draft quote cannot be sent either)
    rather than inventing a new rule.
    """


class CustomerEmailMissingError(Exception):
    """The note's customer has no email address on file."""


class NoteEmailSendFailedError(Exception):
    """The configured provider failed to send. Wraps the original
    EmailSendError so callers never see the provider's raw text."""


def send_adjustment_note_email(
    db: Session, note: AdjustmentNote, *, current_user: User | None = None
) -> str:
    """Emails an issued note, with its PDF attached. Returns the address.

    Reuses the existing EmailSender abstraction, the existing PDF
    renderer and the existing event fan-out -- there is no second mail
    path here. Mirrors send_invoice_email_record's structure exactly,
    including its logging discipline: business context is logged, the
    provider's raw error text never reaches the caller.
    """
    from app.email.base import EmailAttachment, EmailMessage, EmailSendError
    from app.email.factory import get_email_sender
    from app.adjustment_note_pdf import render_adjustment_note_pdf
    from app.localization import get_language, t

    if note.status != AdjustmentNoteStatus.issued.value:
        raise NoteNotSendableError(note.id)

    recipient = note.customer_email_snapshot or (
        note.customer.email if note.customer is not None else None
    )
    if not recipient:
        raise CustomerEmailMissingError(note.id)

    sender = get_email_sender()
    pdf_bytes = render_adjustment_note_pdf(note)
    language = get_language(note)
    kind = t(
        language,
        "credit_note_title"
        if AdjustmentNoteType(note.note_type) is AdjustmentNoteType.credit
        else "debit_note_title",
    )
    subject = f"{kind} {note.formatted_number}"

    message = EmailMessage(
        to=recipient,
        subject=subject,
        text_body=t(language, "note_email_body").format(
            note_number=note.formatted_number,
            organization=note.organization.business_name or note.organization.name,
        ),
        attachments=[EmailAttachment(filename=f"{note.formatted_number}.pdf", content=pdf_bytes)],
    )

    logger.info(
        "send_adjustment_note_email: sending organization_id=%s note_id=%s",
        note.organization_id,
        note.id,
    )
    try:
        sender.send(message)
    except EmailSendError as exc:
        logger.error(
            "send_adjustment_note_email: failed organization_id=%s note_id=%s "
            "exception_type=%s exception_message=%s",
            note.organization_id,
            note.id,
            type(exc).__name__,
            str(exc),
        )
        raise NoteEmailSendFailedError(note.id) from exc

    _emit(db, note, WebhookEventType.adjustment_note_sent, current_user)
    db.commit()
    return recipient
