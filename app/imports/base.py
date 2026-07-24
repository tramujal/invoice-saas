"""Shared preview/confirm orchestration — the two-step workflow glue.
Entity modules provide FieldSpec list + a per-row processor callback +
(for confirm) a persist callback; this module never knows what a
"customer" (or future "product"/"invoice") is.

Preview-state strategy: there is no server-side token or cache at all.
Both preview and confirm independently re-derive everything from the raw
uploaded bytes (see app/routers/customer_imports.py) — the frontend keeps
the picked file in memory and resends it, with its chosen mapping, on
confirm. This is simpler than an in-memory store tied to one process (
nothing to expire, nothing lost on redeploy, nothing to scope to a
user+org+TTL) and it structurally guarantees confirm never trusts anything
the client says about row validity from the preview response — it isn't
even given the chance to.

Transaction strategy: rows that fail Python-side validation or duplicate
detection never reach the database at all. Valid/warning rows are
persisted one at a time, each inside its own `db.begin_nested()` savepoint
— entered fresh for each row (never adding a row to the session before
its own savepoint begins) — so a genuinely unexpected DB-level failure on
one row rolls back only that row's savepoint. Exactly one outer
`db.commit()` finalizes every successfully-persisted row at the end;
there is never a per-row commit.
"""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.imports.column_mapping import ImportMappingError, resolve_column_mapping
from app.imports.types import (
    REASON_MISSING_REQUIRED_MAPPING,
    ColumnMappingResult,
    ConfirmResult,
    ConfirmRow,
    ConfirmRowStatus,
    FieldSpec,
    ParsedFile,
    PreviewResult,
    PreviewRow,
    PreviewRowStatus,
)
from app.imports.validation import apply_column_mapping
from app.services.plan_limits import PlanLimitExceededError

logger = logging.getLogger(__name__)

REASON_PLAN_LIMIT_REACHED = "plan_limit_reached"

RowProcessor = Callable[[dict[str, str]], tuple[PreviewRowStatus, str | None]]
PersistFn = Callable[[Session, dict[str, str]], None]

_STATUS_COUNT_FIELD = {
    PreviewRowStatus.valid: "valid_count",
    PreviewRowStatus.warning: "warning_count",
    PreviewRowStatus.invalid: "invalid_count",
    PreviewRowStatus.duplicate: "duplicate_count",
}


def build_preview(
    parsed: ParsedFile,
    field_specs: tuple[FieldSpec, ...],
    manual_mapping: dict[str, str] | None,
    process_row: RowProcessor,
    max_preview_rows: int,
) -> tuple[ColumnMappingResult, PreviewResult]:
    mapping_result = resolve_column_mapping(parsed.headers, field_specs, manual_mapping)

    counts = {"valid_count": 0, "warning_count": 0, "invalid_count": 0, "duplicate_count": 0}
    rows: list[PreviewRow] = []
    for index, raw_row in enumerate(parsed.rows, start=1):
        values = apply_column_mapping(raw_row, mapping_result.mapping)
        if mapping_result.requires_manual_mapping:
            # Rows can't be meaningfully validated without the required
            # field mapped -- every row reports the same reason, and the
            # frontend is expected to fix mapping (step 2) before preview
            # results are actionable.
            status, reason = PreviewRowStatus.invalid, REASON_MISSING_REQUIRED_MAPPING
        else:
            status, reason = process_row(values)

        counts[_STATUS_COUNT_FIELD[status]] += 1
        if len(rows) < max_preview_rows:
            rows.append(PreviewRow(row_number=index, status=status, reason_code=reason, values=values))

    preview = PreviewResult(total_rows=len(parsed.rows), rows=rows, **counts)
    return mapping_result, preview


def build_confirm(
    db: Session,
    parsed: ParsedFile,
    field_specs: tuple[FieldSpec, ...],
    manual_mapping: dict[str, str] | None,
    process_row: RowProcessor,
    persist_row: PersistFn,
) -> ConfirmResult:
    mapping_result = resolve_column_mapping(parsed.headers, field_specs, manual_mapping)
    if mapping_result.requires_manual_mapping:
        raise ImportMappingError(
            REASON_MISSING_REQUIRED_MAPPING, "Required field mapping is missing."
        )

    rows: list[ConfirmRow] = []
    imported = skipped = failed = 0
    for index, raw_row in enumerate(parsed.rows, start=1):
        values = apply_column_mapping(raw_row, mapping_result.mapping)
        status, reason = process_row(values)

        if status in (PreviewRowStatus.valid, PreviewRowStatus.warning):
            try:
                # Entered fresh for this row only -- nothing is added to
                # the session before this point, so a rollback here can
                # never undo an earlier row's already-flushed insert.
                with db.begin_nested():
                    persist_row(db, values)
                rows.append(
                    ConfirmRow(row_number=index, status=ConfirmRowStatus.imported, reason_code=None, values=values)
                )
                imported += 1
            except PlanLimitExceededError:
                # Not an unexpected error -- the organization's plan
                # limit was reached partway through this import. Every
                # row from here on will hit the same cap, so they're all
                # reported the same way rather than logged as failures.
                rows.append(
                    ConfirmRow(
                        row_number=index,
                        status=ConfirmRowStatus.failed,
                        reason_code=REASON_PLAN_LIMIT_REACHED,
                        values=values,
                    )
                )
                failed += 1
            except Exception:
                logger.exception(
                    "customer_import: unexpected DB error on row %d (row values not logged)",
                    index,
                )
                rows.append(
                    ConfirmRow(
                        row_number=index,
                        status=ConfirmRowStatus.failed,
                        reason_code="unexpected_error",
                        values=values,
                    )
                )
                failed += 1
        elif status == PreviewRowStatus.duplicate:
            rows.append(
                ConfirmRow(row_number=index, status=ConfirmRowStatus.skipped, reason_code=reason, values=values)
            )
            skipped += 1
        else:
            rows.append(
                ConfirmRow(row_number=index, status=ConfirmRowStatus.failed, reason_code=reason, values=values)
            )
            failed += 1

    db.commit()
    return ConfirmResult(
        imported_count=imported,
        skipped_duplicate_count=skipped,
        failed_count=failed,
        total_processed=len(parsed.rows),
        rows=rows,
    )
