import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_org_member
from app.email.base import EmailAttachment, EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.email.templates import build_invoice_email
from app.invoice_numbering import INVOICE_NUMBER_PREFIX, format_invoice_number
from app.invoice_pdf import render_invoice_pdf
from app.models import Customer, Invoice, InvoiceLineItem, Organization, User
from app.payment_status import PaymentStatus
from app.schemas import (
    InvoiceCreateRequest,
    InvoicePaymentStatusUpdate,
    InvoiceResponse,
    InvoiceSortField,
    InvoiceSummaryResponse,
    PaginatedInvoicesResponse,
    SendInvoiceEmailResponse,
    SortDirection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations/{organization_id}/invoices", tags=["invoices"])

_SORT_COLUMNS: dict[InvoiceSortField, ColumnElement] = {
    InvoiceSortField.invoice_number: Invoice.invoice_number,
    InvoiceSortField.created_at: Invoice.created_at,
    InvoiceSortField.total: Invoice.total,
    InvoiceSortField.customer_name: Customer.name,
}


def _invoice_number_match(search_term: str) -> int | None:
    """Extracts an exact invoice number from a search term like "5",
    "000005", or "INV-000005". Returns None if, after stripping an optional
    INV- prefix, the term isn't purely numeric (e.g. it's a name search)."""
    term = search_term.strip()
    if term.lower().startswith(INVOICE_NUMBER_PREFIX.lower()):
        term = term[len(INVOICE_NUMBER_PREFIX):]
    term = term.lstrip("0") or "0"
    return int(term) if term.isdigit() else None


def _build_invoice_query(
    organization_id: str,
    search: str | None,
    payment_status: PaymentStatus | None,
    created_after: datetime | None,
    min_total: Decimal | None,
    max_total: Decimal | None,
):
    query = (
        select(Invoice)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.organization_id == organization_id)
    )

    if search and search.strip():
        term = search.strip()
        conditions = [Customer.name.ilike(f"%{term}%")]
        invoice_number = _invoice_number_match(term)
        if invoice_number is not None:
            conditions.append(Invoice.invoice_number == invoice_number)
        query = query.where(or_(*conditions))

    if payment_status is not None:
        query = query.where(Invoice.payment_status == payment_status.value)
    if created_after is not None:
        query = query.where(Invoice.created_at >= created_after)
    if min_total is not None:
        query = query.where(Invoice.total >= min_total)
    if max_total is not None:
        query = query.where(Invoice.total <= max_total)

    return query


def _invoice_in_org(
    db: Session, organization_id: str, invoice_id: str
) -> Invoice:
    invoice = db.scalar(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.organization_id == organization_id,
        )
    )
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found",
        )
    return invoice


@router.get("", response_model=PaginatedInvoicesResponse)
def list_organization_invoices(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255),
    payment_status: PaymentStatus | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    min_total: Decimal | None = Query(default=None, ge=0),
    max_total: Decimal | None = Query(default=None, ge=0),
    sort_by: InvoiceSortField = Query(default=InvoiceSortField.created_at),
    sort_dir: SortDirection = Query(default=SortDirection.desc),
) -> PaginatedInvoicesResponse:
    require_org_member(current_user, organization_id, db)

    base_query = _build_invoice_query(
        organization_id, search, payment_status, created_after, min_total, max_total
    )

    total = db.scalar(
        select(func.count()).select_from(base_query.subquery())
    )
    if total is None:
        total = 0

    sort_column = _SORT_COLUMNS[sort_by]
    if sort_by == InvoiceSortField.customer_name:
        order = (
            sort_column.asc().nulls_last()
            if sort_dir == SortDirection.asc
            else sort_column.desc().nulls_last()
        )
    else:
        order = sort_column.asc() if sort_dir == SortDirection.asc else sort_column.desc()

    rows = db.scalars(
        base_query.options(selectinload(Invoice.customer))
        .order_by(order)
        .limit(limit)
        .offset(offset)
    ).all()

    return PaginatedInvoicesResponse(total=total, items=list(rows))


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    organization_id: str,
    invoice_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_org_member(current_user, organization_id, db)
    invoice = _invoice_in_org(db, organization_id, invoice_id)
    pdf_bytes = render_invoice_pdf(invoice)
    filename = f"{format_invoice_number(invoice.invoice_number)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{invoice_id}/send-email", response_model=SendInvoiceEmailResponse)
def send_invoice_email(
    organization_id: str,
    invoice_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SendInvoiceEmailResponse:
    # Authorization/existence/validation checks happen before we even ask
    # whether the email provider is configured, so a bad request (wrong org,
    # missing invoice, no customer email) always reports its real 403/404/422
    # rather than being masked by a 503 from get_email_sender().
    require_org_member(current_user, organization_id, db)
    invoice = _invoice_in_org(db, organization_id, invoice_id)

    customer = invoice.customer
    if customer is None or not customer.email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This invoice has no customer email on file.",
        )

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
        "send_invoice_email: sending invoice email organization_id=%s "
        "invoice_id=%s recipient=%s",
        organization_id,
        invoice_id,
        customer.email,
    )

    try:
        email_sender.send(message)
    except EmailSendError as exc:
        # Full exception detail (type, message, and — from resend_provider's
        # own logger.exception call — a traceback plus the raw Resend
        # status/body if one was received) is already logged at the source.
        # This line adds the business context (which org/invoice/recipient)
        # so the two log lines can be correlated. The client only ever gets
        # a fixed, generic message — never str(exc), which previously
        # leaked Resend's raw error text to the frontend.
        logger.error(
            "send_invoice_email: failed to send invoice email "
            "organization_id=%s invoice_id=%s recipient=%s "
            "exception_type=%s exception_message=%s",
            organization_id,
            invoice_id,
            customer.email,
            type(exc).__name__,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send invoice email. Please try again later.",
        ) from exc

    logger.info(
        "send_invoice_email: invoice email sent successfully "
        "organization_id=%s invoice_id=%s recipient=%s",
        organization_id,
        invoice_id,
        customer.email,
    )

    return SendInvoiceEmailResponse(sent=True, sent_to=customer.email)


@router.patch("/{invoice_id}", response_model=InvoiceSummaryResponse)
def update_invoice_payment_status(
    organization_id: str,
    invoice_id: str,
    body: InvoicePaymentStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Invoice:
    require_org_member(current_user, organization_id, db)
    invoice = _invoice_in_org(db, organization_id, invoice_id)
    invoice.payment_status = body.payment_status.value
    db.commit()
    db.refresh(invoice)
    return invoice


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


@router.post("", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_invoice(
    organization_id: str,
    body: InvoiceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Invoice:
    require_org_member(current_user, organization_id, db)

    customer_id = body.customer_id
    if customer_id is not None:
        customer = db.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == organization_id,
            )
        )
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found in this organization",
            )

    subtotal = Decimal("0")
    line_models: list[InvoiceLineItem] = []
    for line in body.line_items:
        line_total = _quantize_money(line.quantity * line.unit_price)
        subtotal += line_total
        line_models.append(
            InvoiceLineItem(
                description=line.description,
                quantity=line.quantity,
                unit_price=_quantize_money(line.unit_price),
                line_total=line_total,
            )
        )

    subtotal = _quantize_money(subtotal)
    tax_amount = _quantize_money(subtotal * body.tax_rate)
    total = _quantize_money(subtotal + tax_amount)

    # Locks the organization row so two concurrent invoice creations can't be
    # handed the same next_invoice_number (a real row lock on Postgres; a
    # harmless no-op on SQLite, which serializes writers itself).
    organization = db.execute(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    ).scalar_one()
    invoice_number = organization.next_invoice_number
    organization.next_invoice_number = invoice_number + 1

    invoice = Invoice(
        organization_id=organization_id,
        invoice_number=invoice_number,
        created_by_user_id=current_user.id,
        customer_id=customer_id,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        line_items=line_models,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice
