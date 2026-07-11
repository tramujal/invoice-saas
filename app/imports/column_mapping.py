"""Header normalization and column-to-field mapping — entity-agnostic.
Given a set of FieldSpec (declared by an entity module, e.g.
app.imports.customers.CUSTOMER_FIELD_SPECS) and the file's detected
headers, resolves an automatic mapping and merges in any manual override
from the client, validating it strictly (never trusting the client to
supply something consistent).
"""

import unicodedata

from app.imports.types import REASON_DUPLICATE_TARGET_MAPPING, ColumnMappingResult, FieldSpec

REASON_INVALID_MAPPING = "invalid_mapping"

IGNORE_TARGET = "ignore"


class ImportMappingError(Exception):
    """Raised with a stable reason_code for a malformed/inconsistent
    client-supplied mapping (unknown column, unknown target field,
    duplicate target assignment)."""

    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        self.message = message
        super().__init__(message)


def normalize_header(value: str) -> str:
    """trim -> strip accents -> casefold, so "Dirección", "direccion", and
    " DIRECCIÓN " all normalize identically. Deliberately simple (no
    fuzzy/partial matching) to avoid ambiguous matches."""
    stripped = value.strip()
    decomposed = unicodedata.normalize("NFKD", stripped)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.casefold()


def _auto_match_columns(headers: list[str], field_specs: tuple[FieldSpec, ...]) -> dict[str, str]:
    """Returns source_header -> target_field ("ignore" if unmatched). Once
    a target field is claimed by one column, later columns whose alias
    would also match that same target are left unmapped rather than
    silently reassigned — avoiding an ambiguous automatic mapping."""
    mapping: dict[str, str] = {}
    claimed: set[str] = set()
    for header in headers:
        normalized = normalize_header(header)
        matched = None
        for spec in field_specs:
            if spec.name in claimed:
                continue
            if normalized in spec.aliases:
                matched = spec.name
                break
        mapping[header] = matched or IGNORE_TARGET
        if matched:
            claimed.add(matched)
    return mapping


def resolve_column_mapping(
    headers: list[str],
    field_specs: tuple[FieldSpec, ...],
    manual_mapping: dict[str, str] | None,
) -> ColumnMappingResult:
    final = _auto_match_columns(headers, field_specs)

    if manual_mapping:
        valid_targets = {spec.name for spec in field_specs} | {IGNORE_TARGET}
        for header, target in manual_mapping.items():
            if header not in headers:
                raise ImportMappingError(
                    REASON_INVALID_MAPPING, f"Unknown column in mapping: {header!r}"
                )
            if target not in valid_targets:
                raise ImportMappingError(
                    REASON_INVALID_MAPPING, f"Unknown target field in mapping: {target!r}"
                )
            final[header] = target

    # Duplicate-target check runs over the FINAL merged mapping (auto +
    # manual), not just the manual override in isolation — two columns
    # can't resolve to the same non-"ignore" target no matter how that
    # came about.
    seen: dict[str, str] = {}
    for header, target in final.items():
        if target == IGNORE_TARGET:
            continue
        if target in seen:
            raise ImportMappingError(
                REASON_DUPLICATE_TARGET_MAPPING,
                f"Both {seen[target]!r} and {header!r} are mapped to {target!r}.",
            )
        seen[target] = header

    missing_required = [
        spec.name
        for spec in field_specs
        if spec.required and spec.name not in final.values()
    ]
    return ColumnMappingResult(
        mapping=final,
        requires_manual_mapping=bool(missing_required),
        missing_required_fields=missing_required,
    )
