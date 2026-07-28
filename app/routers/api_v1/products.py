"""Public API -- Products & Services.

Reuses app.services.products verbatim (create/get/update/archive/
restore) -- plan-limit enforcement (products) and the archive/restore
lifecycle (Product has no hard delete; see Product.active's own
docstring) behave identically to the browser-facing app.routers.products.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api_key_auth import ApiKeyContext, require_api_key_permission
from app.api_key_permissions import ApiKeyPermission
from app.database import get_db
from app.models import Product
from app.product_type import ProductType
from app.routers.api_v1._common import AUTH_RESPONSES, NOT_FOUND_RESPONSE, PLAN_LIMIT_RESPONSE
from app.schemas import (
    PaginatedProductsResponse,
    ProductCreateRequest,
    ProductResponse,
    ProductUpdateRequest,
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

router = APIRouter(prefix="/api/v1/products", tags=["Public API — Products"])


def _product_or_404(db: Session, organization_id: str, product_id: str) -> Product:
    try:
        return get_product_in_org(db, organization_id, product_id)
    except ProductNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product or service",
    responses={**AUTH_RESPONSES, **PLAN_LIMIT_RESPONSE},
)
def create_product(
    body: ProductCreateRequest,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.products_write)),
) -> Product:
    try:
        return create_product_record(
            db,
            context.organization_id,
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


@router.get(
    "",
    response_model=PaginatedProductsResponse,
    summary="List products & services",
    responses=AUTH_RESPONSES,
)
def list_products(
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.products_read)),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=255, description="Matches name or SKU."),
    type: ProductType | None = Query(default=None),
    active: bool | None = Query(default=None),
) -> PaginatedProductsResponse:
    query = select(Product).where(Product.organization_id == context.organization_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(Product.name.ilike(term), Product.sku.ilike(term)))
    if type is not None:
        query = query.where(Product.type == type.value)
    if active is not None:
        query = query.where(Product.active == active)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Product.created_at.desc()).limit(limit).offset(offset)).all()
    return PaginatedProductsResponse(total=total, items=list(rows))


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get a product or service",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.products_read)),
) -> Product:
    return _product_or_404(db, context.organization_id, product_id)


@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update a product or service",
    description="Partial update -- only the fields present in the request body are changed.",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def update_product(
    product_id: str,
    body: ProductUpdateRequest,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.products_write)),
) -> Product:
    product = _product_or_404(db, context.organization_id, product_id)
    changes = body.model_dump(exclude_unset=True)
    for enum_field in ("type", "currency_code"):
        if changes.get(enum_field) is not None:
            changes[enum_field] = changes[enum_field].value
    return update_product_record(db, product, changes)


@router.post(
    "/{product_id}/archive",
    response_model=ProductResponse,
    summary="Archive a product or service",
    description="Products have no hard delete -- archiving is the only removal mechanism "
    "(see also /restore).",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE},
)
def archive_product(
    product_id: str,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.products_write)),
) -> Product:
    product = _product_or_404(db, context.organization_id, product_id)
    return archive_product_record(db, product)


@router.post(
    "/{product_id}/restore",
    response_model=ProductResponse,
    summary="Restore an archived product or service",
    responses={**AUTH_RESPONSES, **NOT_FOUND_RESPONSE, **PLAN_LIMIT_RESPONSE},
)
def restore_product(
    product_id: str,
    db: Session = Depends(get_db),
    context: ApiKeyContext = Depends(require_api_key_permission(ApiKeyPermission.products_write)),
) -> Product:
    product = _product_or_404(db, context.organization_id, product_id)
    try:
        return restore_product_record(db, product)
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())
