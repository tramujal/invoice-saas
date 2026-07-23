"""Anonymous, unauthenticated public quote endpoints -- view, download PDF,
accept, reject. No organization_id anywhere in these URLs: the token alone
resolves the quote (see get_quote_by_public_token), and it is never scoped
by anything else. Every mutating action is rate-limited by IP (see
app.rate_limit.ip_identity) since there is no logged-in user to key on.

Suspended organizations (see app.organization_status): view/pdf stay
available -- read-only, and breaking an already-issued customer link over
an internal platform action the customer had no part in is needless
collateral damage. accept/reject are blocked (see
_ensure_organization_active_for_mutation) -- a mutating business outcome
shouldn't be recorded on behalf of a frozen tenant.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.organization_status import OrganizationStatus
from app.quote_pdf import render_quote_pdf
from app.quote_numbering import format_quote_number
from app.rate_limit import (
    PUBLIC_QUOTE_ACTION_RULES,
    PUBLIC_QUOTE_VIEW_RULES,
    RateLimitCheck,
    enforce_rate_limit,
    ip_identity,
)
from app.schemas import PublicQuoteActionResponse, PublicQuoteResponse
from app.services.platform_settings import get_effective_settings
from app.services.quotes import (
    QuoteAlreadyRespondedError,
    QuoteNotFoundError,
    get_quote_by_public_token,
    mark_quote_accepted_record,
    mark_quote_rejected_record,
)

router = APIRouter(prefix="/quotes/public", tags=["quote_public"])


def _quote_by_token(db: Session, token: str):
    try:
        return get_quote_by_public_token(db, token)
    except QuoteNotFoundError:
        # Never distinguishes "wrong token" from "not found" -- both are
        # exactly the same 404 to an anonymous caller.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")


def _ensure_organization_active_for_mutation(quote) -> None:
    """Blocks accept/reject only -- never view/pdf (see this module's
    docstring update below). A suspended tenant shouldn't have new
    business outcomes recorded on its behalf, but a customer who already
    holds this link did nothing wrong and shouldn't lose the ability to
    just look at it."""
    if quote.organization.status == OrganizationStatus.suspended.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "organization_suspended",
                "message": "This organization is not currently accepting responses to quotes.",
            },
        )


def _ensure_not_in_maintenance_mode_for_mutation(db: Session) -> None:
    """Global sibling of _ensure_organization_active_for_mutation -- same
    accept/reject-only, never view/pdf scope, but for the platform-wide
    maintenance switch rather than a per-org one (see app.deps.
    _ensure_not_in_maintenance_mode for the organization-scoped-route
    equivalent). Takes the request's own session explicitly rather than
    letting get_effective_settings open its own -- this route already has
    one open, and a second self-managed connection would contend with it
    for SQLite's single active writer in tests that hold their own
    transaction open."""
    if get_effective_settings(db).maintenance_mode:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "maintenance_mode",
                "message": "The platform is currently undergoing maintenance. Please try again shortly.",
            },
        )


@router.get("/{token}", response_model=PublicQuoteResponse)
def view_public_quote(token: str, request: Request, db: Session = Depends(get_db)) -> PublicQuoteResponse:
    enforce_rate_limit(
        [RateLimitCheck(scope="quotes:public:view", identity=ip_identity(request), rules=PUBLIC_QUOTE_VIEW_RULES)]
    )
    quote = _quote_by_token(db, token)
    return PublicQuoteResponse(
        quote_number=format_quote_number(quote.quote_number),
        organization_name=quote.organization.business_name or quote.organization.name,
        customer_name=quote.customer_name,
        subtotal=quote.subtotal,
        tax_rate=quote.tax_rate,
        tax_amount=quote.tax_amount,
        total=quote.total,
        effective_status=quote.effective_status,
        currency_code=quote.currency_code,
        language=quote.language,
        issue_date=quote.issue_date,
        expiry_date=quote.expiry_date,
        notes=quote.notes,
        line_items=list(quote.line_items),
    )


@router.get("/{token}/pdf")
def download_public_quote_pdf(token: str, request: Request, db: Session = Depends(get_db)) -> Response:
    enforce_rate_limit(
        [RateLimitCheck(scope="quotes:public:view", identity=ip_identity(request), rules=PUBLIC_QUOTE_VIEW_RULES)]
    )
    quote = _quote_by_token(db, token)
    pdf_bytes = render_quote_pdf(quote)
    filename = f"{format_quote_number(quote.quote_number)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{token}/accept", response_model=PublicQuoteActionResponse)
def accept_public_quote(token: str, request: Request, db: Session = Depends(get_db)) -> PublicQuoteActionResponse:
    enforce_rate_limit(
        [RateLimitCheck(scope="quotes:public:accept", identity=ip_identity(request), rules=PUBLIC_QUOTE_ACTION_RULES)]
    )
    quote = _quote_by_token(db, token)
    _ensure_organization_active_for_mutation(quote)
    _ensure_not_in_maintenance_mode_for_mutation(db)
    try:
        quote = mark_quote_accepted_record(db, quote)
    except QuoteAlreadyRespondedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "quote_already_responded",
                "message": "This quote is not currently awaiting a response.",
            },
        )
    return PublicQuoteActionResponse(status=quote.effective_status)


@router.post("/{token}/reject", response_model=PublicQuoteActionResponse)
def reject_public_quote(token: str, request: Request, db: Session = Depends(get_db)) -> PublicQuoteActionResponse:
    enforce_rate_limit(
        [RateLimitCheck(scope="quotes:public:reject", identity=ip_identity(request), rules=PUBLIC_QUOTE_ACTION_RULES)]
    )
    quote = _quote_by_token(db, token)
    _ensure_organization_active_for_mutation(quote)
    _ensure_not_in_maintenance_mode_for_mutation(db)
    try:
        quote = mark_quote_rejected_record(db, quote)
    except QuoteAlreadyRespondedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "quote_already_responded",
                "message": "This quote is not currently awaiting a response.",
            },
        )
    return PublicQuoteActionResponse(status=quote.effective_status)
