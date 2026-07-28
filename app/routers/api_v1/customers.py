"""Public API -- Customers.

Every write path here calls the exact same app.services.customers
functions the browser-facing app.routers.customers uses, so plan-limit
enforcement (check_limit, inside create_customer_record) and usage
tracking (which reads the same Customer rows live -- see
app.services.organization_usage) apply identically whether a customer
was created from the browser or from this API. Nothing here re-checks a
limit or re-implements a create/update/delete.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api_key_auth import ApiKeyContext, require_api_key_permission
from app.api_key_permissions import ApiKeyPermission
from app.database import get_db
from app.models import Customer
from app.routers.api_v1._common import AUTH_RESPONSES, NOT_FOUND_RESPONSE, PLAN_LIMIT_RESPONSE
from app.schemas import CustomerCreateRequest, CustomerResponse, CustomerUpdateRequest
from app.services.customers import (
    CustomerNotFoundError,
    create_customer_record,
    delete_customer_record,
    get_customer_in_org,
    update_customer_record,
)
from app.services.plan_limits import PlanLimitExceededError

router = APIRouter(prefix="/api/v1/customers", tags=["Public API — Customers"])


def _customer_or_404(db: Session, organization_id: str, customer_id: str) -> Customer:
    try:
        return get_customer_in_org(db, organization_id, customer_id)
    except CustomerNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")


@router.post(
    "",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer",
    description="Creates a customer in the authenticated organization. Subject to the "
    "organization's plan limit for customers.",
    responses={**AUTH_RESPONSES, **PLAN_LIMIT_RESPONSE},
)
def create_customer(
    body: CustomerCreateRequest,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.customers_write)),
) -> Customer:
    try:
        return create_customer_record(
            db, context.organization_id, body.name, body.email, body.phone, body.address, body.tax_id
        )
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())


@router.get(
    "",
    response_model=list[CustomerResponse],
    summary="List customers",
    description="Returns customers in the authenticated organization, newest first.",
    responses=AUTH_RESPONSES,
)
def list_customers(
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.customers_read)),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255, description="Matches name, email, or phone."),
) -> list[Customer]:
    query = select(Customer).where(Customer.organization_id == context.organization_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(Customer.name.ilike(term), Customer.email.ilike(term), Customer.phone.ilike(term)))
    rows = db.scalars(query.order_by(Customer.created_at.desc()).limit(limit).offset(offset)).all()
    return list(rows)


@router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Get a customer",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.customers_read)),
) -> Customer:
    return _customer_or_404(db, context.organization_id, customer_id)


@router.patch(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Update a customer",
    description="Partial update -- only the fields present in the request body are changed.",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def update_customer(
    customer_id: str,
    body: CustomerUpdateRequest,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.customers_write)),
) -> Customer:
    customer = _customer_or_404(db, context.organization_id, customer_id)
    return update_customer_record(db, customer, body.model_dump(exclude_unset=True))


@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a customer",
    description="Permanently deletes a customer. This does not affect invoices/quotes "
    "already issued to them.",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def delete_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.customers_write)),
) -> None:
    customer = _customer_or_404(db, context.organization_id, customer_id)
    delete_customer_record(db, customer)
