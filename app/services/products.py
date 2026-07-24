"""Shared product-catalog business logic.

Extracted the same way app.services.invoices is: reused by more than just
its own router — app.services.invoices (to validate an incoming
product_id on an invoice line) and the AI assistant's product-name
resolution (app/ai/tools/products.py) both call get_product_in_org here,
so there is exactly one lookup implementation, never a second one that
could silently drift.

Raises small, typed exceptions instead of HTTPException, matching
app.services.invoices's own rationale (no FastAPI dependency; each caller
translates independently).
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.currency import get_currency_code
from app.models import Organization, Product
from app.product_type import ProductType
from app.schemas import CurrencyCode
from app.services.plan_limits import LimitedResource, check_limit


class ProductNotFoundError(Exception):
    """No product matches the given id within this organization."""


def get_product_in_org(db: Session, organization_id: str, product_id: str) -> Product:
    product = db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == organization_id,
        )
    )
    if product is None:
        raise ProductNotFoundError(product_id)
    return product


def create_product_record(
    db: Session,
    organization_id: str,
    name: str,
    description: str,
    type_: ProductType,
    sku: str,
    default_unit_price: Decimal,
    currency_code: CurrencyCode | None,
    default_tax_rate: Decimal,
) -> Product:
    check_limit(db, organization_id, LimitedResource.products)
    organization = db.get(Organization, organization_id)
    resolved_currency_code = (
        currency_code.value if currency_code else get_currency_code(organization)
    )
    product = Product(
        organization_id=organization_id,
        name=name,
        description=description,
        type=type_.value,
        sku=sku,
        default_unit_price=default_unit_price,
        currency_code=resolved_currency_code,
        default_tax_rate=default_tax_rate,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def update_product_record(db: Session, product: Product, changes: dict) -> Product:
    """`changes` is an already-validated dict of field -> new value
    (typically `ProductUpdateRequest.model_dump(exclude_unset=True,
    mode="json")` from the router) — enum/decimal values are expected to
    already be plain strings/numbers, matching how
    app.routers.organizations's update endpoint applies its own PATCH."""
    for key, value in changes.items():
        setattr(product, key, value)
    db.commit()
    db.refresh(product)
    return product


def archive_product_record(db: Session, product: Product) -> Product:
    """Idempotent -- archiving an already-archived product is a no-op,
    never an error, since this is the only "removal" path (see
    Product.active's docstring in app/models.py: there is no DELETE)."""
    if product.active:
        product.active = False
        db.commit()
        db.refresh(product)
    return product


def restore_product_record(db: Session, product: Product) -> Product:
    """Restoring an archived product increases the standing active-
    product count exactly like creating a new one does, so it's gated
    by the same limit -- see Product.active's docstring: archive/
    restore is this app's only "removal"/"return" mechanism."""
    if not product.active:
        check_limit(db, product.organization_id, LimitedResource.products)
        product.active = True
        db.commit()
        db.refresh(product)
    return product
