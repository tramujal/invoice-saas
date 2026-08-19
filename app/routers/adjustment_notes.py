"""Credit / debit note endpoints (Phase 29).

ONE unified resource for both note types rather than parallel
/credit-notes and /debit-notes trees: the two share every field, every
lifecycle transition and every query, so splitting them would duplicate
the whole router to express one enum. Callers filter with ?note_type=.

PERMISSIONS reuse the invoice family deliberately -- a credit note is an
invoice correction, not a new capability, and someone trusted to issue an
invoice is by definition trusted to correct one. Adding note.* permissions
would force every existing role and test fixture to be revisited for no
security gain:

    read   -> Permission.invoice_read
    create -> Permission.invoice_create   (create, issue, void)
    send   -> Permission.invoice_send     (reserved for Pass 2 email)
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adjustment_note_pdf import render_adjustment_note_pdf
from app.adjustment_note_status import AdjustmentNoteStatus
from app.adjustment_note_type import AdjustmentNoteType
from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.models import AdjustmentNote, User
from app.permissions import Permission
from app.schemas import (
    AdjustmentNoteCreateRequest,
    AdjustmentNoteResponse,
    InvoiceAdjustmentSummary,
    InvoiceCreditabilityResponse,
    PaginatedAdjustmentNotesResponse,
    SendAdjustmentNoteEmailResponse,
)
from app.services.adjustment_notes import (
    AdjustmentNoteNotFoundError,
    CustomerEmailMissingError,
    DebitLineCannotReferenceSourceError,
    EmptyNoteError,
    LineOverCreditError,
    NoteAlreadyVoidError,
    NoteNotDraftError,
    NoteEmailSendFailedError,
    NoteNotIssuedError,
    NoteNotSendableError,
    OverCreditError,
    SourceInvoiceNotFoundError,
    SourceLineNotOnInvoiceError,
    create_adjustment_note,
    delete_draft_note,
    get_creditable_lines,
    get_invoice_adjustments,
    get_note_in_org,
    issue_adjustment_note,
    send_adjustment_note_email,
    void_adjustment_note,
)
from app.services.invoices import InvoiceNotFoundError, get_invoice_in_org

router = APIRouter(prefix="/organizations/{organization_id}", tags=["adjustment-notes"])


def _serialize(note: AdjustmentNote) -> AdjustmentNoteResponse:
    """Formats the document number once, here, so every surface shows
    "CN-000004" rather than the raw integer."""
    payload = AdjustmentNoteResponse.model_validate(note)
    return payload.model_copy(update={"note_number": note.formatted_number})


def _raise_note_error(exc: Exception) -> None:
    """Maps the service layer's typed errors onto HTTP.

    Over-credit is 409 CONFLICT, not 422: the request is perfectly
    well-formed, it conflicts with the current state of the invoice --
    and that state can change between two identical requests, which is
    exactly what 409 means.
    """
    if isinstance(exc, (OverCreditError, LineOverCreditError)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())
    if isinstance(exc, SourceLineNotOnInvoiceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "source_line_not_on_invoice",
                "message": "A line references an invoice line that is not on the source invoice.",
            },
        )
    if isinstance(exc, DebitLineCannotReferenceSourceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "debit_line_cannot_reference_source",
                "message": "Debit note lines are free-form and cannot reference an invoice line.",
            },
        )
    if isinstance(exc, EmptyNoteError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_note", "message": "A note needs at least one line."},
        )
    if isinstance(exc, NoteNotDraftError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "note_not_draft",
                "message": "Only a draft note can be modified. Issued notes are immutable.",
            },
        )
    if isinstance(exc, NoteAlreadyVoidError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "note_already_void", "message": "This note is already void."},
        )
    if isinstance(exc, NoteNotIssuedError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "note_not_issued", "message": "Only an issued note can be voided."},
        )
    raise exc


# --- creation, from an invoice ----------------------------------------


@router.post(
    "/invoices/{invoice_id}/adjustment-notes/{note_type}",
    response_model=AdjustmentNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_note_for_invoice(
    organization_id: str,
    invoice_id: str,
    note_type: AdjustmentNoteType,
    body: AdjustmentNoteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdjustmentNoteResponse:
    """The ONLY way to create a note: always from a specific invoice, in
    this organization. There is no standalone-note endpoint, which is
    what makes "every note has a valid source invoice in the same tenant"
    a structural property rather than a validation rule."""
    require_permission(current_user, organization_id, Permission.invoice_create, db)
    require_verified_email(current_user)
    try:
        note = create_adjustment_note(
            db,
            organization_id,
            note_type=note_type,
            source_invoice_id=invoice_id,
            line_items=body.line_items,
            reason=body.reason,
            current_user=current_user,
            issue_immediately=body.issue_immediately,
        )
    except SourceInvoiceNotFoundError:
        # Same response as "no such invoice" -- a caller must never be
        # able to distinguish another tenant's invoice from a missing one.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    except Exception as exc:
        _raise_note_error(exc)
    return _serialize(note)


@router.get(
    "/invoices/{invoice_id}/creditability",
    response_model=InvoiceCreditabilityResponse,
)
def get_invoice_creditability(
    organization_id: str,
    invoice_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvoiceCreditabilityResponse:
    """What a credit-note form needs: the document-level ceiling plus how
    much of each line remains creditable."""
    require_permission(current_user, organization_id, Permission.invoice_read, db)
    try:
        invoice = get_invoice_in_org(db, organization_id, invoice_id)
    except InvoiceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return InvoiceCreditabilityResponse(
        summary=InvoiceAdjustmentSummary(**get_invoice_adjustments(db, invoice).__dict__),
        lines=get_creditable_lines(db, invoice),
    )


@router.get("/invoices/{invoice_id}/adjustment-notes", response_model=list[AdjustmentNoteResponse])
def list_notes_for_invoice(
    organization_id: str,
    invoice_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AdjustmentNoteResponse]:
    """Every note attached to one invoice, including drafts and voids --
    the invoice detail page shows the full history, not just what
    currently counts."""
    require_permission(current_user, organization_id, Permission.invoice_read, db)
    try:
        get_invoice_in_org(db, organization_id, invoice_id)
    except InvoiceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    notes = db.scalars(
        select(AdjustmentNote)
        .where(
            AdjustmentNote.organization_id == organization_id,
            AdjustmentNote.source_invoice_id == invoice_id,
        )
        .order_by(AdjustmentNote.created_at.desc())
    ).all()
    return [_serialize(note) for note in notes]


# --- the notes resource -----------------------------------------------


@router.get("/adjustment-notes", response_model=PaginatedAdjustmentNotesResponse)
def list_notes(
    organization_id: str,
    note_type: AdjustmentNoteType | None = None,
    note_status: AdjustmentNoteStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedAdjustmentNotesResponse:
    require_permission(current_user, organization_id, Permission.invoice_read, db)

    filters = [AdjustmentNote.organization_id == organization_id]
    if note_type is not None:
        filters.append(AdjustmentNote.note_type == note_type.value)
    if note_status is not None:
        filters.append(AdjustmentNote.status == note_status.value)

    total = db.scalar(select(func.count(AdjustmentNote.id)).where(*filters)) or 0
    notes = db.scalars(
        select(AdjustmentNote)
        .where(*filters)
        .order_by(AdjustmentNote.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return PaginatedAdjustmentNotesResponse(
        items=[_serialize(note) for note in notes], total=total, limit=limit, offset=offset
    )


@router.get("/adjustment-notes/{note_id}", response_model=AdjustmentNoteResponse)
def get_note(
    organization_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdjustmentNoteResponse:
    require_permission(current_user, organization_id, Permission.invoice_read, db)
    try:
        note = get_note_in_org(db, organization_id, note_id)
    except AdjustmentNoteNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return _serialize(note)


@router.post("/adjustment-notes/{note_id}/issue", response_model=AdjustmentNoteResponse)
def issue_note(
    organization_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdjustmentNoteResponse:
    """draft -> issued. Re-checks the credit ceiling: the note may have
    sat in draft while other notes were issued against the same invoice."""
    require_permission(current_user, organization_id, Permission.invoice_create, db)
    require_verified_email(current_user)
    try:
        note = get_note_in_org(db, organization_id, note_id)
    except AdjustmentNoteNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    try:
        note = issue_adjustment_note(db, note, current_user=current_user)
    except Exception as exc:
        _raise_note_error(exc)
    return _serialize(note)


@router.post("/adjustment-notes/{note_id}/void", response_model=AdjustmentNoteResponse)
def void_note(
    organization_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdjustmentNoteResponse:
    """issued -> void. The note is retained and stays in history; it
    simply stops counting, which also frees the ceiling it consumed."""
    require_permission(current_user, organization_id, Permission.invoice_create, db)
    require_verified_email(current_user)
    try:
        note = get_note_in_org(db, organization_id, note_id)
    except AdjustmentNoteNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    try:
        note = void_adjustment_note(db, note, current_user=current_user)
    except Exception as exc:
        _raise_note_error(exc)
    return _serialize(note)


@router.delete("/adjustment-notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    organization_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Drafts only. An issued note is voided, never deleted -- financial
    history is not erased in this application."""
    require_permission(current_user, organization_id, Permission.invoice_create, db)
    require_verified_email(current_user)
    try:
        note = get_note_in_org(db, organization_id, note_id)
    except AdjustmentNoteNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    try:
        delete_draft_note(db, note, current_user=current_user)
    except Exception as exc:
        _raise_note_error(exc)


@router.get("/adjustment-notes/{note_id}/pdf")
def download_note_pdf(
    organization_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Available for any status, including draft and void -- an operator
    needs to be able to look at what a note says before issuing it, and
    after voiding it."""
    require_permission(current_user, organization_id, Permission.invoice_read, db)
    try:
        note = get_note_in_org(db, organization_id, note_id)
    except AdjustmentNoteNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    pdf = render_adjustment_note_pdf(note)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{note.formatted_number}.pdf"'},
    )


@router.post("/adjustment-notes/{note_id}/send-email", response_model=SendAdjustmentNoteEmailResponse)
def send_note_email(
    organization_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SendAdjustmentNoteEmailResponse:
    """Emails an ISSUED note with its PDF attached. Gated on
    Permission.invoice_send, matching how invoices and quotes are sent."""
    require_permission(current_user, organization_id, Permission.invoice_send, db)
    require_verified_email(current_user)
    try:
        note = get_note_in_org(db, organization_id, note_id)
    except AdjustmentNoteNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    try:
        recipient = send_adjustment_note_email(db, note, current_user=current_user)
    except NoteNotSendableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "note_not_sendable",
                "message": "Only an issued note can be emailed.",
            },
        )
    except CustomerEmailMissingError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "customer_email_missing",
                "message": "This note's customer has no email address on file.",
            },
        )
    except NoteEmailSendFailedError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "email_send_failed", "message": "The email provider failed to send."},
        )
    return SendAdjustmentNoteEmailResponse(sent_to=recipient, note_number=note.formatted_number)
