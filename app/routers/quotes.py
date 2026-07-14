from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.currency import CurrencyRequiredError, ProductCurrencyMismatchError
from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.invoice_numbering import format_invoice_number
from app.models import Customer, Quote, User
from app.permissions import Permission
from app.quote_numbering import format_quote_number, parse_quote_number
from app.quote_pdf import render_quote_pdf
from app.quote_status import QuoteStatus
from app.rate_limit import (
    SEND_QUOTE_EMAIL_RULES,
    RateLimitCheck,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
from app.schemas import (
    ConvertQuoteToInvoiceResponse,
    PaginatedQuotesResponse,
    QuoteCreateRequest,
    QuoteResponse,
    QuoteSortField,
    QuoteSummaryResponse,
    QuoteUpdateRequest,
    SendQuoteEmailResponse,
    SortDirection,
)
from app.services.quotes import (
    CustomerEmailMissingError,
    CustomerNotFoundInOrgError,
    EmailSendFailedError,
    ExpiryDateBeforeIssueDateError,
    ProductNotFoundInOrgError,
    QuoteAlreadyConvertedError,
    QuoteAlreadyRespondedError,
    QuoteNotAcceptedError,
    QuoteNotDraftError,
    QuoteNotFoundError,
    archive_quote_record,
    convert_quote_to_invoice,
    create_quote_record,
    delete_draft_quote_record,
    duplicate_quote_record,
    get_customer_in_org,
    get_quote_in_org,
    mark_quote_accepted_record,
    mark_quote_rejected_record,
    restore_quote_record,
    send_quote_record,
    update_quote_record,
)

router = APIRouter(prefix="/organizations/{organization_id}/quotes", tags=["quotes"])

_SORT_COLUMNS: dict[QuoteSortField, ColumnElement] = {
    QuoteSortField.quote_number: Quote.quote_number,
    QuoteSortField.created_at: Quote.created_at,
    QuoteSortField.total: Quote.total,
    QuoteSortField.customer_name: Customer.name,
    QuoteSortField.expiry_date: Quote.expiry_date,
}


def _build_quote_query(
    organization_id: str,
    search: str | None,
    status_filter: QuoteStatus | None,
    active: bool | None,
    created_after: datetime | None,
):
    query = (
        select(Quote)
        .outerjoin(Customer, Quote.customer_id == Customer.id)
        .where(Quote.organization_id == organization_id)
    )

    if search and search.strip():
        term = search.strip()
        conditions = [Customer.name.ilike(f"%{term}%")]
        quote_number = parse_quote_number(term)
        if quote_number is not None:
            conditions.append(Quote.quote_number == quote_number)
        query = query.where(or_(*conditions))

    if status_filter is not None:
        query = query.where(Quote.status == status_filter.value)
    if active is not None:
        query = query.where(Quote.active == active)
    if created_after is not None:
        query = query.where(Quote.created_at >= created_after)

    return query


def _quote_in_org(db: Session, organization_id: str, quote_id: str) -> Quote:
    try:
        return get_quote_in_org(db, organization_id, quote_id)
    except QuoteNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")


@router.get("", response_model=PaginatedQuotesResponse)
def list_organization_quotes(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255),
    status_filter: QuoteStatus | None = Query(default=None, alias="status"),
    active: bool | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    sort_by: QuoteSortField = Query(default=QuoteSortField.created_at),
    sort_dir: SortDirection = Query(default=SortDirection.desc),
) -> PaginatedQuotesResponse:
    require_permission(current_user, organization_id, Permission.quote_read, db)

    base_query = _build_quote_query(
        organization_id, search, status_filter, active, created_after
    )

    total = db.scalar(select(func.count()).select_from(base_query.subquery()))
    if total is None:
        total = 0

    sort_column = _SORT_COLUMNS[sort_by]
    if sort_by in (QuoteSortField.customer_name, QuoteSortField.expiry_date):
        order = (
            sort_column.asc().nulls_last()
            if sort_dir == SortDirection.asc
            else sort_column.desc().nulls_last()
        )
    else:
        order = sort_column.asc() if sort_dir == SortDirection.asc else sort_column.desc()

    rows = db.scalars(
        base_query.options(selectinload(Quote.customer))
        .order_by(order)
        .limit(limit)
        .offset(offset)
    ).all()

    return PaginatedQuotesResponse(total=total, items=list(rows))


@router.get("/{quote_id}", response_model=QuoteResponse)
def get_quote(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Quote:
    require_permission(current_user, organization_id, Permission.quote_read, db)
    return _quote_in_org(db, organization_id, quote_id)


@router.get("/{quote_id}/pdf")
def download_quote_pdf(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_permission(current_user, organization_id, Permission.quote_read, db)
    quote = _quote_in_org(db, organization_id, quote_id)
    pdf_bytes = render_quote_pdf(quote)
    filename = f"{format_quote_number(quote.quote_number)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
def create_quote(
    organization_id: str,
    body: QuoteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Quote:
    require_permission(current_user, organization_id, Permission.quote_create, db)
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

    try:
        return create_quote_record(
            db,
            organization_id,
            current_user,
            customer,
            body.currency_code,
            body.line_items,
            body.tax_rate,
            body.expiry_date,
            body.notes,
        )
    except ExpiryDateBeforeIssueDateError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "expiry_date_before_issue_date",
                "message": "Expiry date cannot be before today.",
            },
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


@router.patch("/{quote_id}", response_model=QuoteResponse)
def update_quote(
    organization_id: str,
    quote_id: str,
    body: QuoteUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Quote:
    require_permission(current_user, organization_id, Permission.quote_edit, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)

    changes = body.model_dump(exclude_unset=True)
    customer_kwarg: dict = {}
    if "customer_id" in changes:
        customer_id = changes.pop("customer_id")
        customer: Customer | None = None
        if customer_id is not None:
            try:
                customer = get_customer_in_org(db, organization_id, customer_id)
            except CustomerNotFoundInOrgError:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Customer not found in this organization",
                )
        customer_kwarg["customer"] = customer

    expiry_kwarg: dict = {}
    if "expiry_date" in changes:
        expiry_kwarg["expiry_date"] = changes.pop("expiry_date")

    try:
        return update_quote_record(
            db,
            organization_id,
            quote,
            # Pulled from the still-typed `body` (not `changes`, which is a
            # plain dict from model_dump()) -- update_quote_record and the
            # totals/currency helpers it calls need real QuoteLineItemCreate
            # objects with attribute access, not nested dicts.
            line_items=body.line_items if "line_items" in changes else None,
            tax_rate=changes.get("tax_rate"),
            notes=changes.get("notes"),
            **customer_kwarg,
            **expiry_kwarg,
        )
    except ExpiryDateBeforeIssueDateError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "expiry_date_before_issue_date",
                "message": "Expiry date cannot be before today.",
            },
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


@router.post("/{quote_id}/archive", response_model=QuoteSummaryResponse)
def archive_quote(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Quote:
    require_permission(current_user, organization_id, Permission.quote_edit, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)
    return archive_quote_record(db, quote)


@router.post("/{quote_id}/restore", response_model=QuoteSummaryResponse)
def restore_quote(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Quote:
    require_permission(current_user, organization_id, Permission.quote_edit, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)
    return restore_quote_record(db, quote)


@router.delete("/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quote(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_permission(current_user, organization_id, Permission.quote_edit, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)
    try:
        delete_draft_quote_record(db, quote)
    except QuoteNotDraftError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "quote_not_draft",
                "message": "Only draft quotes can be deleted. Archive it instead.",
            },
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{quote_id}/duplicate", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
def duplicate_quote(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Quote:
    require_permission(current_user, organization_id, Permission.quote_edit, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)
    return duplicate_quote_record(db, organization_id, current_user, quote)


@router.post("/{quote_id}/mark-accepted", response_model=QuoteSummaryResponse)
def mark_quote_accepted(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Quote:
    """Manual acceptance action -- for a customer who confirmed by phone
    or email rather than through the public accept link. Only legal from
    effective_status == sent (see app.services.quotes._require_sent)."""
    require_permission(current_user, organization_id, Permission.quote_edit, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)
    try:
        return mark_quote_accepted_record(db, quote)
    except QuoteAlreadyRespondedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "quote_already_responded",
                "message": "This quote is not currently awaiting a response.",
            },
        )


@router.post("/{quote_id}/mark-rejected", response_model=QuoteSummaryResponse)
def mark_quote_rejected(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Quote:
    require_permission(current_user, organization_id, Permission.quote_edit, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)
    try:
        return mark_quote_rejected_record(db, quote)
    except QuoteAlreadyRespondedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "quote_already_responded",
                "message": "This quote is not currently awaiting a response.",
            },
        )


@router.post("/{quote_id}/convert", response_model=ConvertQuoteToInvoiceResponse)
def convert_quote(
    organization_id: str,
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConvertQuoteToInvoiceResponse:
    require_permission(current_user, organization_id, Permission.quote_convert, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)
    try:
        result = convert_quote_to_invoice(db, organization_id, quote, current_user)
    except QuoteNotAcceptedError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "quote_not_accepted",
                "message": "Only accepted quotes can be converted into invoices.",
            },
        )
    except QuoteAlreadyConvertedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "quote_already_converted",
                "message": "This quote has already been converted into an invoice.",
            },
        )
    return ConvertQuoteToInvoiceResponse(
        invoice_id=result.invoice.id,
        invoice_number=format_invoice_number(result.invoice.invoice_number),
    )


@router.post("/{quote_id}/send-email", response_model=SendQuoteEmailResponse)
def send_quote_email(
    organization_id: str,
    quote_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SendQuoteEmailResponse:
    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="quotes:send_email:user",
                identity=user_identity(current_user.id),
                rules=SEND_QUOTE_EMAIL_RULES,
            ),
            RateLimitCheck(
                scope="quotes:send_email:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=SEND_QUOTE_EMAIL_RULES,
            ),
        ]
    )

    require_permission(current_user, organization_id, Permission.quote_send, db)
    require_verified_email(current_user)
    quote = _quote_in_org(db, organization_id, quote_id)

    try:
        return send_quote_record(db, quote)
    except CustomerEmailMissingError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This quote has no customer email on file.",
        )
    except EmailSendFailedError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send quote email. Please try again later.",
        )
