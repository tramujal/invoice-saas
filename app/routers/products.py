from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.models import Product, User
from app.permissions import Permission
from app.product_type import ProductType
from app.schemas import (
    PaginatedProductsResponse,
    ProductCreateRequest,
    ProductResponse,
    ProductSortField,
    ProductUpdateRequest,
    SortDirection,
)
from app.services.plan_limits import PlanLimitExceededError
from app.services.products import (
    ProductNotFoundError,
    archive_product_record,
    create_product_record,
    get_product_in_org,
    restore_product_record,
    update_product_record,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/products", tags=["products"]
)

_SORT_COLUMNS: dict[ProductSortField, ColumnElement] = {
    ProductSortField.name: Product.name,
    ProductSortField.created_at: Product.created_at,
    ProductSortField.default_unit_price: Product.default_unit_price,
}


def _product_or_404(db: Session, organization_id: str, product_id: str) -> Product:
    try:
        return get_product_in_org(db, organization_id, product_id)
    except ProductNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    organization_id: str,
    body: ProductCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Product:
    require_permission(current_user, organization_id, Permission.product_write, db)
    require_verified_email(current_user)
    try:
        return create_product_record(
            db,
            organization_id,
            body.name,
            body.description,
            body.type,
            body.sku,
            body.default_unit_price,
            body.currency_code,
            body.default_tax_rate,
        )
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())


@router.get("", response_model=PaginatedProductsResponse)
def list_products(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255),
    type: ProductType | None = Query(default=None),
    active: bool | None = Query(default=None),
    min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
    sort_by: ProductSortField = Query(default=ProductSortField.created_at),
    sort_dir: SortDirection = Query(default=SortDirection.desc),
) -> PaginatedProductsResponse:
    require_permission(current_user, organization_id, Permission.product_read, db)

    query = select(Product).where(Product.organization_id == organization_id)

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(Product.name.ilike(term), Product.sku.ilike(term)))
    if type is not None:
        query = query.where(Product.type == type.value)
    if active is not None:
        query = query.where(Product.active == active)
    if min_price is not None:
        query = query.where(Product.default_unit_price >= min_price)
    if max_price is not None:
        query = query.where(Product.default_unit_price <= max_price)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    if total is None:
        total = 0

    sort_column = _SORT_COLUMNS[sort_by]
    order = sort_column.asc() if sort_dir == SortDirection.asc else sort_column.desc()

    rows = db.scalars(query.order_by(order).limit(limit).offset(offset)).all()
    return PaginatedProductsResponse(total=total, items=list(rows))


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(
    organization_id: str,
    product_id: str,
    body: ProductUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Product:
    require_permission(current_user, organization_id, Permission.product_write, db)
    require_verified_email(current_user)
    product = _product_or_404(db, organization_id, product_id)
    # Deliberately NOT mode="json": that would stringify the Decimal
    # fields (default_unit_price/default_tax_rate), which must stay real
    # Decimal instances when set directly on the ORM row. The `type`/
    # `currency_code` enums need their plain .value instead, mirroring
    # update_invoice_payment_status_record's identical explicit `.value`
    # convention elsewhere in this codebase.
    changes = body.model_dump(exclude_unset=True)
    for enum_field in ("type", "currency_code"):
        if changes.get(enum_field) is not None:
            changes[enum_field] = changes[enum_field].value
    return update_product_record(db, product, changes)


@router.post("/{product_id}/archive", response_model=ProductResponse)
def archive_product(
    organization_id: str,
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Product:
    require_permission(current_user, organization_id, Permission.product_write, db)
    require_verified_email(current_user)
    product = _product_or_404(db, organization_id, product_id)
    return archive_product_record(db, product)


@router.post("/{product_id}/restore", response_model=ProductResponse)
def restore_product(
    organization_id: str,
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Product:
    require_permission(current_user, organization_id, Permission.product_write, db)
    require_verified_email(current_user)
    product = _product_or_404(db, organization_id, product_id)
    try:
        return restore_product_record(db, product)
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())
