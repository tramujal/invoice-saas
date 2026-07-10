from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member, require_verified_email
from app.models import Customer, User
from app.schemas import (
    CustomerCreateRequest,
    CustomerResponse,
    CustomerSortField,
    CustomerUpdateRequest,
    SortDirection,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/customers", tags=["customers"]
)

_SORT_COLUMNS: dict[CustomerSortField, ColumnElement] = {
    CustomerSortField.name: Customer.name,
    CustomerSortField.email: Customer.email,
    CustomerSortField.created_at: Customer.created_at,
}


def _customer_in_org(db: Session, organization_id: str, customer_id: str) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
        )
    )
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    return customer


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    organization_id: str,
    body: CustomerCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Customer:
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)
    customer = Customer(
        organization_id=organization_id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        address=body.address,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("", response_model=list[CustomerResponse])
def list_customers(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: str | None = Query(default=None, max_length=255),
    sort_by: CustomerSortField = Query(default=CustomerSortField.created_at),
    sort_dir: SortDirection = Query(default=SortDirection.desc),
) -> list[Customer]:
    require_org_member(current_user, organization_id, db)

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
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)
    customer = _customer_in_org(db, organization_id, customer_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        setattr(customer, key, value)
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    organization_id: str,
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)
    customer = _customer_in_org(db, organization_id, customer_id)
    db.delete(customer)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
