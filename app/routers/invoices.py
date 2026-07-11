from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_org_member, require_verified_email
from app.invoice_numbering import format_invoice_number, parse_invoice_number
from app.invoice_pdf import render_invoice_pdf
from app.models import Customer, Invoice, User
from app.payment_status import PaymentStatus
from app.rate_limit import (
    SEND_INVOICE_EMAIL_RULES,
    RateLimitCheck,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
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
from app.services.invoices import (
    CustomerEmailMissingError,
    CustomerNotFoundInOrgError,
    EmailSendFailedError,
    InvoiceNotFoundError,
    create_invoice_record,
    get_customer_in_org,
    get_invoice_in_org,
    send_invoice_email_record,
    update_invoice_payment_status_record,
)

router = APIRouter(prefix="/organizations/{organization_id}/invoices", tags=["invoices"])

_SORT_COLUMNS: dict[InvoiceSortField, ColumnElement] = {
    InvoiceSortField.invoice_number: Invoice.invoice_number,
    InvoiceSortField.created_at: Invoice.created_at,
    InvoiceSortField.total: Invoice.total,
    InvoiceSortField.customer_name: Customer.name,
}


# Kept as a thin local alias (rather than importing parse_invoice_number
# under two names) so existing call sites in this file don't need to
# change; the actual logic lives in app.invoice_numbering, shared with the
# AI assistant's invoice-lookup tools (see app/ai/tools/invoices.py).
_invoice_number_match = parse_invoice_number


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
    """Thin HTTP wrapper around the shared app.services.invoices lookup --
    the actual query (and the AI assistant's identical lookup) lives there;
    this only translates "not found" into this router's existing 404
    shape so every call site below keeps working unchanged."""
    try:
        return get_invoice_in_org(db, organization_id, invoice_id)
    except InvoiceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found",
        )


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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SendInvoiceEmailResponse:
    # Rate limit first, before any DB/authorization work: two independent
    # 10/hour buckets (user-only and user+IP), same rationale as
    # resend-verification — a user-only bucket can't be evaded by switching
    # IPs, while the user+IP bucket still surfaces single-source abuse.
    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="invoices:send_email:user",
                identity=user_identity(current_user.id),
                rules=SEND_INVOICE_EMAIL_RULES,
            ),
            RateLimitCheck(
                scope="invoices:send_email:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=SEND_INVOICE_EMAIL_RULES,
            ),
        ]
    )

    # Authorization/existence/validation checks happen before we even ask
    # whether the email provider is configured, so a bad request (wrong org,
    # missing invoice, no customer email) always reports its real 403/404/422
    # rather than being masked by a 503 from get_email_sender().
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)
    invoice = _invoice_in_org(db, organization_id, invoice_id)

    try:
        return send_invoice_email_record(db, invoice)
    except CustomerEmailMissingError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This invoice has no customer email on file.",
        )
    except EmailSendFailedError:
        # The real failure (type, message, and — from resend_provider's own
        # logger.exception call — a traceback plus the raw Resend
        # status/body if one was received) is already logged inside
        # send_invoice_email_record. The client only ever gets a fixed,
        # generic message here — never the underlying exception text, which
        # could leak the provider's raw error to the frontend.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send invoice email. Please try again later.",
        )


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
    return update_invoice_payment_status_record(db, invoice, body.payment_status)


@router.post("", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_invoice(
    organization_id: str,
    body: InvoiceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Invoice:
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)

    customer: Customer | None = None
    if body.customer_id is not None:
        try:
            customer = get_customer_in_org(db, organization_id, body.customer_id)
        except CustomerNotFoundInOrgError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found in this organization",
            )

    return create_invoice_record(
        db,
        organization_id,
        current_user,
        customer,
        body.currency_code,
        body.line_items,
        body.tax_rate,
    )
