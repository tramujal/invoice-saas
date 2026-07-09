from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user, require_org_member
from app.invoice_numbering import format_invoice_number
from app.invoice_pdf import render_invoice_pdf
from app.models import Customer, Invoice, InvoiceLineItem, Organization, User
from app.schemas import (
    InvoiceCreateRequest,
    InvoicePaymentStatusUpdate,
    InvoiceResponse,
    InvoiceSummaryResponse,
    PaginatedInvoicesResponse,
)

router = APIRouter(prefix="/organizations/{organization_id}/invoices", tags=["invoices"])


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
) -> PaginatedInvoicesResponse:
    require_org_member(current_user, organization_id, db)

    org_filter = Invoice.organization_id == organization_id

    total = db.scalar(select(func.count()).select_from(Invoice).where(org_filter))
    if total is None:
        total = 0

    rows = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(org_filter)
        .order_by(Invoice.created_at.desc())
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
