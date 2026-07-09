from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member
from app.models import Customer, User
from app.schemas import CustomerCreateRequest, CustomerResponse, CustomerUpdateRequest

router = APIRouter(
    prefix="/organizations/{organization_id}/customers", tags=["customers"]
)


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
) -> list[Customer]:
    require_org_member(current_user, organization_id, db)
    return list(
        db.scalars(
            select(Customer)
            .where(Customer.organization_id == organization_id)
            .order_by(Customer.created_at.desc())
        ).all()
    )


@router.patch("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    organization_id: str,
    customer_id: str,
    body: CustomerUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Customer:
    require_org_member(current_user, organization_id, db)
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
    customer = _customer_in_org(db, organization_id, customer_id)
    db.delete(customer)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
