"""Product-specific import configuration: supported fields, aliases, row
validation, duplicate detection, and persistence -- a sibling module to
app.imports.customers, shaped exactly the same way (that module's own
docstring promises this). Everything else (parsing, column matching,
preview/confirm orchestration) comes from the shared app.imports.* modules.
"""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.currency import SUPPORTED_CURRENCIES, get_currency_code
from app.imports.types import FieldSpec, PreviewRowStatus
from app.imports.validation import validate_row_fields
from app.localization import get_language, t
from app.models import Organization, Product
from app.product_type import ProductType
from app.services.plan_limits import LimitedResource, check_limit

REASON_INVALID_PRICE = "invalid_price"
REASON_INVALID_TAX_RATE = "invalid_tax_rate"
REASON_INVALID_CURRENCY = "invalid_currency"
REASON_INVALID_TYPE = "invalid_type"
REASON_DUPLICATE_SKU = "duplicate_sku"

# Aliases pre-normalized (trim/casefold/strip-accent) to match
# app.imports.column_mapping.normalize_header()'s output, same convention
# as CUSTOMER_FIELD_SPECS.
PRODUCT_FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="name",
        required=True,
        max_length=255,
        aliases=("name", "product name", "item", "nombre", "producto", "articulo"),
    ),
    FieldSpec(
        name="description",
        required=False,
        max_length=1024,
        aliases=("description", "details", "descripcion", "detalle"),
    ),
    FieldSpec(
        name="type",
        required=False,
        max_length=16,
        aliases=("type", "kind", "tipo"),
    ),
    FieldSpec(
        name="sku",
        required=False,
        max_length=64,
        aliases=("sku", "code", "item code", "codigo", "referencia"),
    ),
    FieldSpec(
        name="default_unit_price",
        required=False,
        max_length=32,
        aliases=("price", "unit price", "default price", "precio", "precio unitario"),
    ),
    FieldSpec(
        name="currency_code",
        required=False,
        max_length=8,
        aliases=("currency", "currency code", "moneda"),
    ),
    FieldSpec(
        name="default_tax_rate",
        required=False,
        max_length=16,
        aliases=("tax rate", "tax", "impuesto", "tasa de impuesto"),
    ),
)

_TYPE_ALIASES: dict[str, str] = {
    "product": ProductType.product.value,
    "products": ProductType.product.value,
    "producto": ProductType.product.value,
    "productos": ProductType.product.value,
    "service": ProductType.service.value,
    "services": ProductType.service.value,
    "servicio": ProductType.service.value,
    "servicios": ProductType.service.value,
}


def _price_validator(value: str) -> str | None:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return REASON_INVALID_PRICE
    return None if parsed >= 0 else REASON_INVALID_PRICE


def _tax_rate_validator(value: str) -> str | None:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return REASON_INVALID_TAX_RATE
    return None if Decimal("0") <= parsed <= Decimal("1") else REASON_INVALID_TAX_RATE


def _currency_validator(value: str) -> str | None:
    return None if value.strip().upper() in SUPPORTED_CURRENCIES else REASON_INVALID_CURRENCY


def _type_validator(value: str) -> str | None:
    return None if value.strip().lower() in _TYPE_ALIASES else REASON_INVALID_TYPE


_CUSTOM_VALIDATORS: dict[str, Callable[[str], str | None]] = {
    "default_unit_price": _price_validator,
    "default_tax_rate": _tax_rate_validator,
    "currency_code": _currency_validator,
    "type": _type_validator,
}


def fetch_existing_skus(db: Session, organization_id: str) -> set[str]:
    """One bounded query for the whole import -- never one query per row.
    Matches app.imports.customers.fetch_existing_keys's exact shape."""
    rows = db.scalars(
        select(Product.sku).where(Product.organization_id == organization_id)
    ).all()
    return {sku.strip().lower() for sku in rows if sku}


def make_row_processor(
    existing_skus: set[str],
) -> Callable[[dict[str, str]], tuple[PreviewRowStatus, str | None]]:
    """SKU duplicate detection only fires when a SKU is actually given --
    an empty SKU is never treated as a duplicate of another empty SKU,
    matching how empty email/tax_id are handled for customers."""
    seen_skus: set[str] = set()

    def process(values: dict[str, str]) -> tuple[PreviewRowStatus, str | None]:
        reasons = validate_row_fields(values, PRODUCT_FIELD_SPECS, _CUSTOM_VALIDATORS)
        if reasons:
            return PreviewRowStatus.invalid, reasons[0]

        sku = values.get("sku", "")
        norm_sku = sku.strip().lower() if sku else None
        if norm_sku and (norm_sku in existing_skus or norm_sku in seen_skus):
            return PreviewRowStatus.duplicate, REASON_DUPLICATE_SKU
        if norm_sku:
            seen_skus.add(norm_sku)

        return PreviewRowStatus.valid, None

    return process


def make_persist_fn(organization_id: str) -> Callable[[Session, dict[str, str]], None]:
    """Returns a function that adds+flushes exactly one Product row.
    Deliberately does not commit -- app.imports.base.build_confirm owns
    the single outer commit. Values have already passed validate_row_fields
    by the time this runs, so parsing here never needs its own error
    handling -- a malformed value would have already been rejected as
    invalid and never reach persist."""

    def persist(db: Session, values: dict[str, str]) -> None:
        # See app.imports.customers.make_persist_fn's own docstring for
        # why calling check_limit() per row (rather than a separately
        # pre-computed counter) correctly enforces the cap across the
        # whole import.
        check_limit(db, organization_id, LimitedResource.products)
        organization = db.get(Organization, organization_id)
        type_value = _TYPE_ALIASES.get(
            values.get("type", "").strip().lower(), ProductType.service.value
        )
        price_raw = values.get("default_unit_price", "")
        tax_raw = values.get("default_tax_rate", "")
        currency_raw = values.get("currency_code", "")

        product = Product(
            organization_id=organization_id,
            name=values.get("name", ""),
            description=values.get("description", ""),
            type=type_value,
            sku=values.get("sku", ""),
            default_unit_price=Decimal(price_raw) if price_raw else Decimal("0"),
            currency_code=currency_raw.strip().upper()
            if currency_raw
            else get_currency_code(organization),
            default_tax_rate=Decimal(tax_raw) if tax_raw else Decimal("0"),
        )
        db.add(product)
        db.flush()

    return persist


def build_template_labels_and_example(organization: Organization) -> tuple[list[str], list[str]]:
    """Labels + one example row for the downloadable CSV/XLSX templates --
    sourced from PRODUCT_FIELD_SPECS's own field order, exactly like
    app.imports.customers.build_template_labels_and_example."""
    language = get_language(organization)
    label_by_field = {
        "name": t(language, "import_product_template_name_label"),
        "description": t(language, "import_product_template_description_label"),
        "type": t(language, "import_product_template_type_label"),
        "sku": t(language, "import_product_template_sku_label"),
        "default_unit_price": t(language, "import_product_template_price_label"),
        "currency_code": t(language, "import_product_template_currency_label"),
        "default_tax_rate": t(language, "import_product_template_tax_rate_label"),
    }
    example_by_field = {
        "name": t(language, "import_product_template_example_name"),
        "description": t(language, "import_product_template_example_description"),
        "type": t(language, "import_product_template_example_type"),
        "sku": t(language, "import_product_template_example_sku"),
        "default_unit_price": t(language, "import_product_template_example_price"),
        "currency_code": get_currency_code(organization),
        "default_tax_rate": t(language, "import_product_template_example_tax_rate"),
    }
    labels = [label_by_field[spec.name] for spec in PRODUCT_FIELD_SPECS]
    example_row = [example_by_field[spec.name] for spec in PRODUCT_FIELD_SPECS]
    return labels, example_row
