"""Entity-agnostic types shared by every import (Customers today; Products/
Services/Suppliers/Inventory/Invoices later). Nothing here knows what a
"customer" is — that lives in app/imports/customers.py.
"""

from dataclasses import dataclass, field
from enum import Enum


class ImportFileType(str, Enum):
    csv = "csv"
    xlsx = "xlsx"


class PreviewRowStatus(str, Enum):
    valid = "valid"
    warning = "warning"
    invalid = "invalid"
    duplicate = "duplicate"


class ConfirmRowStatus(str, Enum):
    imported = "imported"
    skipped = "skipped"
    failed = "failed"


# Reason codes owned by the shared layer (file/mapping-level problems).
# Entity modules (e.g. app.imports.customers) define their own row-level
# reason codes (missing_required_name, invalid_email, ...) — both sets are
# just strings from the frontend's point of view, translated the same way.
REASON_UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
REASON_FILE_TOO_LARGE = "file_too_large"
REASON_TOO_MANY_ROWS = "too_many_rows"
REASON_MALFORMED_FILE = "malformed_file"
REASON_EMPTY_FILE = "empty_file"
REASON_MISSING_REQUIRED_MAPPING = "missing_required_mapping"
REASON_DUPLICATE_TARGET_MAPPING = "duplicate_target_mapping"


@dataclass(frozen=True)
class FieldSpec:
    """One importable target field, declared by an entity module.

    `aliases` must already be in the same normalized form
    column_mapping.normalize_header() produces (trim/casefold/strip-accent)
    — see CUSTOMER_FIELD_SPECS for the canonical example.
    """

    name: str
    required: bool
    max_length: int | None
    aliases: tuple[str, ...]


@dataclass
class ParsedFile:
    """The result of parsing raw upload bytes — before any column mapping
    or row validation. `rows` are keyed by the RAW (not normalized) header
    string exactly as it appeared in the file, with fully-empty rows
    already removed."""

    file_type: ImportFileType
    headers: list[str]
    rows: list[dict[str, str]]


@dataclass
class ColumnMappingResult:
    # source header -> target field name, or "ignore"
    mapping: dict[str, str]
    requires_manual_mapping: bool
    missing_required_fields: list[str]


@dataclass
class PreviewRow:
    row_number: int
    status: PreviewRowStatus
    reason_code: str | None
    values: dict[str, str | None]


@dataclass
class PreviewResult:
    total_rows: int
    valid_count: int
    warning_count: int
    invalid_count: int
    duplicate_count: int
    rows: list[PreviewRow] = field(default_factory=list)


@dataclass
class ConfirmRow:
    row_number: int
    status: ConfirmRowStatus
    reason_code: str | None
    values: dict[str, str | None]


@dataclass
class ConfirmResult:
    imported_count: int
    skipped_duplicate_count: int
    failed_count: int
    total_processed: int
    rows: list[ConfirmRow] = field(default_factory=list)
