"""Generic per-row field-validation engine — entity-agnostic. Entity
modules supply a FieldSpec list and a dict of custom per-field validators;
this module does the actual required/length checking and calls the custom
validators, returning stable reason codes. Duplicate detection and overall
row-status decisions (valid/warning/invalid/duplicate) are entity-specific
and live in the entity module (e.g. app.imports.customers) instead, since
"what counts as a duplicate" or "what counts as a warning" genuinely
differs per entity.
"""

from collections.abc import Callable

from app.imports.types import FieldSpec


def apply_column_mapping(row: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    """Projects a raw row (keyed by source header) into target-field
    values (keyed by target field name), using the resolved mapping.
    Ignored/unmapped columns are dropped."""
    values: dict[str, str] = {}
    for header, target in mapping.items():
        if target == "ignore":
            continue
        values[target] = (row.get(header) or "").strip()
    return values


def validate_row_fields(
    values: dict[str, str],
    field_specs: tuple[FieldSpec, ...],
    custom_validators: dict[str, Callable[[str], str | None]],
) -> list[str]:
    """Returns a list of reason codes for this row's individual field
    values (required/length/format) — empty if none. Required-field
    reasons are named `missing_required_<field>` (e.g.
    `missing_required_name`), matching the exact code the customer import
    needs, and generalizing for free to any future entity's required
    fields. `custom_validators` maps field name -> a function returning a
    reason code string on failure, or None when the value is fine.
    """
    reasons: list[str] = []
    for spec in field_specs:
        value = values.get(spec.name, "")
        if spec.required and not value:
            reasons.append(f"missing_required_{spec.name}")
            continue
        if not value:
            continue
        if spec.max_length is not None and len(value) > spec.max_length:
            reasons.append(f"{spec.name}_too_long")
            continue
        validator = custom_validators.get(spec.name)
        if validator:
            reason = validator(value)
            if reason:
                reasons.append(reason)
    return reasons
