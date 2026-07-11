"""Customer-specific import configuration: supported fields, aliases, row
validation, duplicate detection, and persistence. Everything else
(parsing, column matching, preview/confirm orchestration) comes from the
shared app.imports.* modules — this is the only file that knows what a
"customer" is.

A future Products/Services/Suppliers/Inventory/Invoices import adds a
sibling module shaped exactly like this one (its own FIELD_SPECS, row
processor, and persist function) and a thin router calling
app.imports.base's build_preview/build_confirm — nothing here changes.
"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_validation import (
    is_valid_email_format,
    normalize_customer_email,
    normalize_tax_id,
)
from app.imports.types import FieldSpec, PreviewRowStatus
from app.imports.validation import validate_row_fields
from app.localization import get_language, t
from app.models import Customer, Organization

REASON_MISSING_CONTACT_INFO = "missing_contact_info"
REASON_INVALID_EMAIL = "invalid_email"
REASON_DUPLICATE_EMAIL = "duplicate_email"
REASON_DUPLICATE_TAX_ID = "duplicate_tax_id"

# Aliases are pre-normalized (trim/casefold/strip-accent) to match
# app.imports.column_mapping.normalize_header()'s output exactly, so an
# accented and non-accented variant (e.g. "Dirección"/"Direccion") share a
# single entry here.
CUSTOMER_FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="name",
        required=True,
        max_length=255,
        aliases=(
            "name",
            "customer name",
            "client name",
            "company",
            "business name",
            "nombre",
            "cliente",
            "razon social",
            "empresa",
        ),
    ),
    FieldSpec(
        name="email",
        required=False,
        max_length=255,
        aliases=(
            "email",
            "e-mail",
            "mail",
            "correo",
            "correo electronico",
        ),
    ),
    FieldSpec(
        name="phone",
        required=False,
        max_length=64,
        aliases=(
            "phone",
            "telephone",
            "mobile",
            "cellphone",
            "telefono",
            "celular",
            "movil",
        ),
    ),
    FieldSpec(
        name="address",
        required=False,
        max_length=512,
        aliases=(
            "address",
            "street address",
            "direccion",
            "domicilio",
        ),
    ),
    FieldSpec(
        name="tax_id",
        required=False,
        max_length=64,
        aliases=(
            "tax id",
            "vat",
            "vat number",
            "rut",
            "cuit",
            "nif",
            "cif",
            "cnpj",
            "identificacion fiscal",
        ),
    ),
)


def _email_validator(value: str) -> str | None:
    return None if is_valid_email_format(value) else REASON_INVALID_EMAIL


_CUSTOM_VALIDATORS: dict[str, Callable[[str], str | None]] = {"email": _email_validator}


def fetch_existing_keys(db: Session, organization_id: str) -> tuple[set[str], set[str]]:
    """One combined, bounded query for the whole import — never one query
    per row. Returns (normalized_emails, normalized_tax_ids) for every
    existing customer already in this organization."""
    rows = db.execute(
        select(Customer.email, Customer.tax_id).where(
            Customer.organization_id == organization_id
        )
    ).all()
    emails = {normalize_customer_email(email) for email, _tax_id in rows if email}
    tax_ids = {normalize_tax_id(tax_id) for _email, tax_id in rows if tax_id}
    return emails, tax_ids


def make_row_processor(
    existing_emails: set[str], existing_tax_ids: set[str]
) -> Callable[[dict[str, str]], tuple[PreviewRowStatus, str | None]]:
    """Builds a stateful per-row processor: field validation first (name
    required + format/length rules), then duplicate detection against
    both the DB (existing_*, fetched once by the caller) and rows already
    seen earlier in THIS file (accumulated as rows are processed in
    order, so the first occurrence of a new email/tax_id wins and later
    repeats are the ones reported as duplicates).
    """
    seen_emails: set[str] = set()
    seen_tax_ids: set[str] = set()

    def process(values: dict[str, str]) -> tuple[PreviewRowStatus, str | None]:
        reasons = validate_row_fields(values, CUSTOMER_FIELD_SPECS, _CUSTOM_VALIDATORS)
        if reasons:
            return PreviewRowStatus.invalid, reasons[0]

        email = values.get("email", "")
        tax_id = values.get("tax_id", "")
        norm_email = normalize_customer_email(email) if email else None
        norm_tax_id = normalize_tax_id(tax_id) if tax_id else None

        if norm_email and (norm_email in existing_emails or norm_email in seen_emails):
            return PreviewRowStatus.duplicate, REASON_DUPLICATE_EMAIL
        if norm_tax_id and (norm_tax_id in existing_tax_ids or norm_tax_id in seen_tax_ids):
            return PreviewRowStatus.duplicate, REASON_DUPLICATE_TAX_ID

        if norm_email:
            seen_emails.add(norm_email)
        if norm_tax_id:
            seen_tax_ids.add(norm_tax_id)

        if not email and not values.get("phone"):
            return PreviewRowStatus.warning, REASON_MISSING_CONTACT_INFO
        return PreviewRowStatus.valid, None

    return process


def make_persist_fn(organization_id: str) -> Callable[[Session, dict[str, str]], None]:
    """Returns a function that adds+flushes exactly one Customer row.
    Deliberately does not commit — app.imports.base.build_confirm owns the
    single outer commit, and wraps each call to this function in its own
    db.begin_nested() savepoint."""

    def persist(db: Session, values: dict[str, str]) -> None:
        customer = Customer(
            organization_id=organization_id,
            name=values.get("name", ""),
            email=values.get("email", ""),
            phone=values.get("phone", ""),
            address=values.get("address", ""),
            tax_id=values.get("tax_id", ""),
        )
        db.add(customer)
        db.flush()

    return persist


def build_template_labels_and_example(organization: Organization) -> tuple[list[str], list[str]]:
    """Labels + one example row for the downloadable CSV/XLSX templates —
    sourced from CUSTOMER_FIELD_SPECS's own field order (so the template
    can never drift from what the parser actually recognizes) plus the
    organization's language and tax_label setting (reusing the exact label
    already shown in Settings/PDFs, per the "if using the organization's
    tax-label setting is clean, reuse it" guidance) — never a second,
    hardcoded header list.
    """
    language = get_language(organization)
    label_by_field = {
        "name": t(language, "import_template_name_label"),
        "email": t(language, "import_template_email_label"),
        "phone": t(language, "import_template_phone_label"),
        "address": t(language, "import_template_address_label"),
        "tax_id": organization.tax_label,
    }
    example_by_field = {
        "name": t(language, "import_template_example_name"),
        "email": t(language, "import_template_example_email"),
        "phone": t(language, "import_template_example_phone"),
        "address": t(language, "import_template_example_address"),
        "tax_id": t(language, "import_template_example_tax_id"),
    }
    labels = [label_by_field[spec.name] for spec in CUSTOMER_FIELD_SPECS]
    example_row = [example_by_field[spec.name] for spec in CUSTOMER_FIELD_SPECS]
    return labels, example_row
