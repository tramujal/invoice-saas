"""Public API -- Invoices.

Reuses app.services.invoices verbatim (create/get/update-payment-status)
-- plan-limit enforcement (invoices/month), numbering, totals, and
currency resolution all behave identically to the browser-facing
app.routers.invoices. There is no invoice DELETE in this API version:
app.services.invoices defines no hard-delete function at all, so there
is nothing to expose (see Phase 15A's architecture audit) -- inventing
one here would be new business logic, not a reuse of an existing
service.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api_key_auth import ApiKeyContext, require_api_key_permission
from app.api_key_permissions import ApiKeyPermission
from app.currency import CurrencyRequiredError, ProductCurrencyMismatchError
from app.database import get_db
from app.models import Invoice
from app.payment_status import PaymentStatus
from app.routers.api_v1._common import AUTH_RESPONSES, NOT_FOUND_RESPONSE, PLAN_LIMIT_RESPONSE
from app.schemas import (
    InvoiceCreateRequest,
    InvoicePaymentStatusUpdate,
    InvoiceResponse,
    InvoiceSummaryResponse,
    PaginatedInvoicesResponse,
)
from app.services.invoices import (
    CustomerNotFoundInOrgError,
    DueDateBeforeIssueDateError,
    InvoiceNotFoundError,
    ProductNotFoundInOrgError,
    create_invoice_record,
    get_customer_in_org,
    get_invoice_in_org,
    update_invoice_payment_status_record,
)
from app.services.plan_limits import PlanLimitExceededError

router = APIRouter(prefix="/api/v1/invoices", tags=["Public API — Invoices"])


def _invoice_or_404(db: Session, organization_id: str, invoice_id: str) -> Invoice:
    try:
        return get_invoice_in_org(db, organization_id, invoice_id)
    except InvoiceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")


@router.post(
    "",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an invoice",
    responses={**AUTH_RESPONSES, **PLAN_LIMIT_RESPONSE},
)
def create_invoice(
    body: InvoiceCreateRequest,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.invoices_write)),
) -> Invoice:
    customer = None
    if body.customer_id is not None:
        try:
            customer = get_customer_in_org(db, context.organization_id, body.customer_id)
        except CustomerNotFoundInOrgError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found in this organization"
            )

    try:
        return create_invoice_record(
            db,
            context.organization_id,
            None,
            customer,
            body.currency_code,
            body.line_items,
            body.tax_rate,
            body.due_date,
        )
    except DueDateBeforeIssueDateError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "due_date_before_issue_date", "message": "Due date cannot be before the issue date."},
        )
    except ProductNotFoundInOrgError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "product_not_found",
                "message": "One of the selected products was not found in this organization.",
            },
        )
    except CurrencyRequiredError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "currency_required",
                "message": "A currency is required when every line item is a manual line.",
            },
        )
    except ProductCurrencyMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "product_currency_mismatch",
                "message": (
                    f"'{exc.product_name}' is priced in {exc.product_currency}, "
                    f"but this document is in {exc.document_currency}."
                ),
            },
        )
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())


@router.get(
    "",
    response_model=PaginatedInvoicesResponse,
    summary="List invoices",
    responses=AUTH_RESPONSES,
)
def list_invoices(
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.invoices_read)),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    payment_status: PaymentStatus | None = Query(default=None),
) -> PaginatedInvoicesResponse:
    query = select(Invoice).where(Invoice.organization_id == context.organization_id)
    if payment_status is not None:
        query = query.where(Invoice.payment_status == payment_status.value)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Invoice.created_at.desc()).limit(limit).offset(offset)).all()
    return PaginatedInvoicesResponse(total=total, items=list(rows))


@router.get(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Get an invoice",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def get_invoice(
    invoice_id: str,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.invoices_read)),
) -> Invoice:
    return _invoice_or_404(db, context.organization_id, invoice_id)


@router.patch(
    "/{invoice_id}",
    response_model=InvoiceSummaryResponse,
    summary="Update an invoice's payment status",
    description="The only mutable field on an existing invoice -- everything else "
    "(line items, totals, customer) is fixed at creation time.",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def update_invoice_payment_status(
    invoice_id: str,
    body: InvoicePaymentStatusUpdate,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.invoices_write)),
) -> Invoice:
    invoice = _invoice_or_404(db, context.organization_id, invoice_id)
    return update_invoice_payment_status_record(db, invoice, body.payment_status)
