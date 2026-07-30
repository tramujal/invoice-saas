"""Shared customer CRUD business logic.

Extracted from app.routers.customers (which used to inline all of this)
so a second caller -- the public API (app.routers.api_v1.customers) --
can reuse the exact same create/update/delete logic instead of a second,
drifting copy. Mirrors app.services.products's own shape and rationale
exactly: small typed exceptions instead of HTTPException (no FastAPI
dependency here), each caller translates independently.

Note: app.services.quotes and app.services.invoices each already define
their own tiny `get_customer_in_org`/`CustomerNotFoundInOrgError` pair,
used only to resolve a customer_id referenced from a quote/invoice line.
This module's `CustomerNotFoundError` is a separate, pre-existing-style
duplication (matching how app.services.products.ProductNotFoundError
already coexists with quotes/invoices' own ProductNotFoundInOrgError) --
not something this change touches or consolidates.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer
from app.schemas import CustomerResponse
from app.services.plan_limits import LimitedResource, check_limit
from app.notifications.service import emit_event
from app.webhook_event_type import WebhookEventType


class CustomerNotFoundError(Exception):
    """No customer matches the given id within this organization."""


def get_customer_in_org(db: Session, organization_id: str, customer_id: str) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
        )
    )
    if customer is None:
        raise CustomerNotFoundError(customer_id)
    return customer


def create_customer_record(
    db: Session,
    organization_id: str,
    name: str,
    email: str,
    phone: str,
    address: str,
    tax_id: str,
    actor_user_id: str | None = None,
) -> Customer:
    check_limit(db, organization_id, LimitedResource.customers)
    customer = Customer(
        organization_id=organization_id,
        name=name,
        email=email,
        phone=phone,
        address=address,
        tax_id=tax_id,
    )
    db.add(customer)
    db.flush()
    emit_event(
        db,
        organization_id=organization_id,
        event_type=WebhookEventType.customer_created,
        object_type="customer",
        object_id=customer.id,
        payload=CustomerResponse.model_validate(customer).model_dump(mode="json"),
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(customer)
    return customer


def update_customer_record(
    db: Session, customer: Customer, changes: dict, actor_user_id: str | None = None
) -> Customer:
    """`changes` is an already-validated dict of field -> new value,
    typically `CustomerUpdateRequest.model_dump(exclude_unset=True)` --
    matches app.services.products.update_product_record's own contract."""
    for key, value in changes.items():
        if value is None:
            continue
        setattr(customer, key, value)
    emit_event(
        db,
        organization_id=customer.organization_id,
        event_type=WebhookEventType.customer_updated,
        object_type="customer",
        object_id=customer.id,
        payload=CustomerResponse.model_validate(customer).model_dump(mode="json"),
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(customer)
    return customer


def delete_customer_record(
    db: Session, customer: Customer, actor_user_id: str | None = None
) -> None:
    """Hard delete -- Customer has no archive/restore lifecycle (unlike
    Product), so this is the one genuine DELETE in the customer/product/
    quote/invoice family. Matches the exact behavior the browser router
    already had before this extraction. The event payload is snapshotted
    BEFORE db.delete() -- there is no row left to read from afterward."""
    payload = CustomerResponse.model_validate(customer).model_dump(mode="json")
    emit_event(
        db,
        organization_id=customer.organization_id,
        event_type=WebhookEventType.customer_deleted,
        object_type="customer",
        object_id=customer.id,
        payload=payload,
        actor_user_id=actor_user_id,
    )
    db.delete(customer)
    db.commit()
