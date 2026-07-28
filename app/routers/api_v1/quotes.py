"""Public API -- Quotes.

Reuses app.services.quotes verbatim (create/get/update/delete-draft) --
plan-limit enforcement (quotes/month), numbering, totals, and currency
resolution all behave identically to the browser-facing
app.routers.quotes, since both call the exact same functions.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api_key_auth import ApiKeyContext, require_api_key_permission
from app.api_key_permissions import ApiKeyPermission
from app.currency import CurrencyRequiredError, ProductCurrencyMismatchError
from app.database import get_db
from app.models import Quote
from app.quote_status import QuoteStatus
from app.routers.api_v1._common import AUTH_RESPONSES, NOT_FOUND_RESPONSE, PLAN_LIMIT_RESPONSE
from app.schemas import PaginatedQuotesResponse, QuoteCreateRequest, QuoteResponse, QuoteUpdateRequest
from app.services.plan_limits import PlanLimitExceededError
from app.services.quotes import (
    CustomerNotFoundInOrgError,
    ExpiryDateBeforeIssueDateError,
    ProductNotFoundInOrgError,
    QuoteNotDraftError,
    QuoteNotFoundError,
    create_quote_record,
    delete_draft_quote_record,
    get_customer_in_org,
    get_quote_in_org,
    update_quote_record,
)

router = APIRouter(prefix="/api/v1/quotes", tags=["Public API — Quotes"])


def _quote_or_404(db: Session, organization_id: str, quote_id: str) -> Quote:
    try:
        return get_quote_in_org(db, organization_id, quote_id)
    except QuoteNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")


def _resolve_customer(db: Session, organization_id: str, customer_id: str | None):
    if customer_id is None:
        return None
    try:
        return get_customer_in_org(db, organization_id, customer_id)
    except CustomerNotFoundInOrgError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found in this organization"
        )


def _document_error_responses(exc: Exception) -> HTTPException:
    if isinstance(exc, ExpiryDateBeforeIssueDateError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "expiry_date_before_issue_date", "message": "Expiry date cannot be before today."},
        )
    if isinstance(exc, ProductNotFoundInOrgError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "product_not_found",
                "message": "One of the selected products was not found in this organization.",
            },
        )
    if isinstance(exc, CurrencyRequiredError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "currency_required",
                "message": "A currency is required when every line item is a manual line.",
            },
        )
    if isinstance(exc, ProductCurrencyMismatchError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "product_currency_mismatch",
                "message": (
                    f"'{exc.product_name}' is priced in {exc.product_currency}, "
                    f"but this document is in {exc.document_currency}."
                ),
            },
        )
    raise exc


@router.post(
    "",
    response_model=QuoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a quote",
    responses={**AUTH_RESPONSES, **PLAN_LIMIT_RESPONSE},
)
def create_quote(
    body: QuoteCreateRequest,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.quotes_write)),
) -> Quote:
    customer = _resolve_customer(db, context.organization_id, body.customer_id)
    try:
        return create_quote_record(
            db,
            context.organization_id,
            None,
            customer,
            body.currency_code,
            body.line_items,
            body.tax_rate,
            body.expiry_date,
            body.notes,
        )
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())
    except (
        ExpiryDateBeforeIssueDateError,
        ProductNotFoundInOrgError,
        CurrencyRequiredError,
        ProductCurrencyMismatchError,
    ) as exc:
        raise _document_error_responses(exc)


@router.get(
    "",
    response_model=PaginatedQuotesResponse,
    summary="List quotes",
    responses=AUTH_RESPONSES,
)
def list_quotes(
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.quotes_read)),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: QuoteStatus | None = Query(default=None, alias="status"),
) -> PaginatedQuotesResponse:
    query = select(Quote).where(Quote.organization_id == context.organization_id)
    if status_filter is not None:
        query = query.where(Quote.status == status_filter.value)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Quote.created_at.desc()).limit(limit).offset(offset)).all()
    return PaginatedQuotesResponse(total=total, items=list(rows))


@router.get(
    "/{quote_id}",
    response_model=QuoteResponse,
    summary="Get a quote",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def get_quote(
    quote_id: str,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.quotes_read)),
) -> Quote:
    return _quote_or_404(db, context.organization_id, quote_id)


@router.patch(
    "/{quote_id}",
    response_model=QuoteResponse,
    summary="Update a quote",
    description="Partial update -- only the fields present in the request body are changed.",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def update_quote(
    quote_id: str,
    body: QuoteUpdateRequest,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.quotes_write)),
) -> Quote:
    quote = _quote_or_404(db, context.organization_id, quote_id)
    changes = body.model_dump(exclude_unset=True)

    customer_kwarg: dict = {}
    if "customer_id" in changes:
        customer_kwarg["customer"] = _resolve_customer(db, context.organization_id, changes.pop("customer_id"))

    expiry_kwarg: dict = {}
    if "expiry_date" in changes:
        expiry_kwarg["expiry_date"] = changes.pop("expiry_date")

    try:
        return update_quote_record(
            db,
            context.organization_id,
            quote,
            line_items=body.line_items if "line_items" in changes else None,
            tax_rate=changes.get("tax_rate"),
            notes=changes.get("notes"),
            **customer_kwarg,
            **expiry_kwarg,
        )
    except (
        ExpiryDateBeforeIssueDateError,
        ProductNotFoundInOrgError,
        CurrencyRequiredError,
        ProductCurrencyMismatchError,
    ) as exc:
        raise _document_error_responses(exc)


@router.delete(
    "/{quote_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a draft quote",
    description="Only draft quotes can be deleted -- a quote that has been sent, accepted, "
    "rejected, or converted must be archived instead (not available in this API version).",
    responses={
        **AUTH_RESPONSES,
        **NOT_FOUND_RESPONSE,
        409: {
            "description": "The quote is not a draft.",
            "content": {"application/json": {"example": {"detail": "Only draft quotes can be deleted"}}},
        },
    },
)
def delete_quote(
    quote_id: str,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.quotes_write)),
) -> None:
    quote = _quote_or_404(db, context.organization_id, quote_id)
    try:
        delete_draft_quote_record(db, quote)
    except QuoteNotDraftError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft quotes can be deleted")
