from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.models import Customer, User
from app.permissions import Permission
from app.schemas import (
    CustomerCreateRequest,
    CustomerResponse,
    CustomerSortField,
    CustomerUpdateRequest,
    SortDirection,
)
from app.services.customers import (
    CustomerNotFoundError,
    create_customer_record,
    delete_customer_record,
    get_customer_in_org,
    update_customer_record,
)
from app.services.plan_limits import PlanLimitExceededError

router = APIRouter(
    prefix="/organizations/{organization_id}/customers", tags=["customers"]
)

_SORT_COLUMNS: dict[CustomerSortField, ColumnElement] = {
    CustomerSortField.name: Customer.name,
    CustomerSortField.email: Customer.email,
    CustomerSortField.created_at: Customer.created_at,
}


def _customer_or_404(db: Session, organization_id: str, customer_id: str) -> Customer:
    try:
        return get_customer_in_org(db, organization_id, customer_id)
    except CustomerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    organization_id: str,
    body: CustomerCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Customer:
    require_permission(current_user, organization_id, Permission.customer_write, db)
    require_verified_email(current_user)
    try:
        return create_customer_record(
            db, organization_id, body.name, body.email, body.phone, body.address, body.tax_id
        )
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())


@router.get("", response_model=list[CustomerResponse])
def list_customers(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: str | None = Query(default=None, max_length=255),
    sort_by: CustomerSortField = Query(default=CustomerSortField.created_at),
    sort_dir: SortDirection = Query(default=SortDirection.desc),
) -> list[Customer]:
    require_permission(current_user, organization_id, Permission.customer_read, db)

    query = select(Customer).where(Customer.organization_id == organization_id)

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Customer.name.ilike(term),
                Customer.email.ilike(term),
                Customer.phone.ilike(term),
            )
        )

    sort_column = _SORT_COLUMNS[sort_by]
    order = sort_column.asc() if sort_dir == SortDirection.asc else sort_column.desc()

    return list(db.scalars(query.order_by(order)).all())


@router.patch("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    organization_id: str,
    customer_id: str,
    body: CustomerUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Customer:
    require_permission(current_user, organization_id, Permission.customer_write, db)
    require_verified_email(current_user)
    customer = _customer_or_404(db, organization_id, customer_id)
    return update_customer_record(db, customer, body.model_dump(exclude_unset=True))


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    organization_id: str,
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_permission(current_user, organization_id, Permission.customer_write, db)
    require_verified_email(current_user)
    customer = _customer_or_404(db, organization_id, customer_id)
    delete_customer_record(db, customer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
