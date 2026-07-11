"""Customer CSV/XLSX import: preview, confirm, and template download.

Preview-state strategy: no server-side token/cache — see the module
docstring in app/imports/base.py for why. Both preview and confirm parse
the uploaded bytes independently; confirm never trusts anything the
client says about a row's validity from a prior preview call.
"""

import hashlib
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member, require_verified_email
from app.imports.base import build_confirm, build_preview
from app.imports.column_mapping import ImportMappingError
from app.imports.customers import (
    CUSTOMER_FIELD_SPECS,
    build_template_labels_and_example,
    fetch_existing_keys,
    make_persist_fn,
    make_row_processor,
)
from app.imports.limits import IMPORT_MAX_FILE_SIZE_BYTES, IMPORT_MAX_PREVIEW_ROWS, IMPORT_MAX_ROWS
from app.imports.parsers import ImportFileError, parse_upload
from app.imports.templates import build_csv_template, build_xlsx_template
from app.imports.types import REASON_FILE_TOO_LARGE, REASON_UNSUPPORTED_FILE_TYPE
from app.models import Organization, User
from app.rate_limit import (
    IMPORT_CONFIRM_RULES,
    IMPORT_PREVIEW_RULES,
    RateLimitCheck,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
from app.schemas import ImportConfirmResponse, ImportPreviewResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/organizations/{organization_id}/customers/import", tags=["customer-imports"]
)


def _hash(value: str) -> str:
    """Never logs a raw organization/user id — only a short, stable,
    non-reversible fingerprint, matching app.rate_limit's own convention."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _organization_or_404(db: Session, organization_id: str) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


def _file_error_status(reason_code: str) -> int:
    if reason_code == REASON_FILE_TOO_LARGE:
        return status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    if reason_code == REASON_UNSUPPORTED_FILE_TYPE:
        return status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    return status.HTTP_400_BAD_REQUEST


def _parse_mapping_form_field(mapping: str | None) -> dict[str, str] | None:
    if mapping is None or not mapping.strip():
        return None
    try:
        parsed = json.loads(mapping)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_mapping", "message": "Column mapping is not valid JSON."},
        )
    if not isinstance(parsed, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_mapping",
                "message": "Column mapping must be a JSON object of column name to target field.",
            },
        )
    return parsed


@router.post("/preview", response_model=ImportPreviewResponse)
def preview_customer_import(
    organization_id: str,
    request: Request,
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportPreviewResponse:
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)

    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="imports:customers:preview:user",
                identity=user_identity(current_user.id),
                rules=IMPORT_PREVIEW_RULES,
            ),
            RateLimitCheck(
                scope="imports:customers:preview:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=IMPORT_PREVIEW_RULES,
            ),
        ]
    )

    manual_mapping = _parse_mapping_form_field(mapping)
    content = file.file.read()

    try:
        parsed = parse_upload(
            file.filename or "",
            content,
            max_bytes=IMPORT_MAX_FILE_SIZE_BYTES,
            max_rows=IMPORT_MAX_ROWS,
        )
    except ImportFileError as exc:
        raise HTTPException(
            status_code=_file_error_status(exc.reason_code),
            detail={"code": exc.reason_code, "message": exc.message},
        )

    existing_emails, existing_tax_ids = fetch_existing_keys(db, organization_id)
    process_row = make_row_processor(existing_emails, existing_tax_ids)

    try:
        mapping_result, preview = build_preview(
            parsed, CUSTOMER_FIELD_SPECS, manual_mapping, process_row, IMPORT_MAX_PREVIEW_ROWS
        )
    except ImportMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.reason_code, "message": exc.message},
        )

    normalized_headers = [h.strip() for h in parsed.headers]

    logger.info(
        "customer_import_preview: organization_id_hash=%s user_id_hash=%s file_type=%s "
        "total_rows=%d valid=%d warning=%d invalid=%d duplicate=%d",
        _hash(organization_id),
        _hash(current_user.id),
        parsed.file_type.value,
        preview.total_rows,
        preview.valid_count,
        preview.warning_count,
        preview.invalid_count,
        preview.duplicate_count,
    )

    return ImportPreviewResponse(
        file_type=parsed.file_type.value,
        headers=parsed.headers,
        normalized_headers=normalized_headers,
        auto_mapping=mapping_result.mapping,
        requires_manual_mapping=mapping_result.requires_manual_mapping,
        missing_required_fields=mapping_result.missing_required_fields,
        total_rows=preview.total_rows,
        preview_rows=[
            {
                "row_number": row.row_number,
                "status": row.status.value,
                "reason_code": row.reason_code,
                "values": row.values,
            }
            for row in preview.rows
        ],
        valid_count=preview.valid_count,
        warning_count=preview.warning_count,
        invalid_count=preview.invalid_count,
        duplicate_count=preview.duplicate_count,
    )


@router.post("/confirm", response_model=ImportConfirmResponse)
def confirm_customer_import(
    organization_id: str,
    request: Request,
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportConfirmResponse:
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)

    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="imports:customers:confirm:user",
                identity=user_identity(current_user.id),
                rules=IMPORT_CONFIRM_RULES,
            ),
            RateLimitCheck(
                scope="imports:customers:confirm:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=IMPORT_CONFIRM_RULES,
            ),
        ]
    )

    manual_mapping = _parse_mapping_form_field(mapping)
    content = file.file.read()

    try:
        parsed = parse_upload(
            file.filename or "",
            content,
            max_bytes=IMPORT_MAX_FILE_SIZE_BYTES,
            max_rows=IMPORT_MAX_ROWS,
        )
    except ImportFileError as exc:
        raise HTTPException(
            status_code=_file_error_status(exc.reason_code),
            detail={"code": exc.reason_code, "message": exc.message},
        )

    existing_emails, existing_tax_ids = fetch_existing_keys(db, organization_id)
    process_row = make_row_processor(existing_emails, existing_tax_ids)
    persist_row = make_persist_fn(organization_id)

    try:
        result = build_confirm(db, parsed, CUSTOMER_FIELD_SPECS, manual_mapping, process_row, persist_row)
    except ImportMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.reason_code, "message": exc.message},
        )

    logger.info(
        "customer_import_confirm: organization_id_hash=%s user_id_hash=%s file_type=%s "
        "imported=%d skipped_duplicate=%d failed=%d total_processed=%d",
        _hash(organization_id),
        _hash(current_user.id),
        parsed.file_type.value,
        result.imported_count,
        result.skipped_duplicate_count,
        result.failed_count,
        result.total_processed,
    )

    return ImportConfirmResponse(
        imported_count=result.imported_count,
        skipped_duplicate_count=result.skipped_duplicate_count,
        failed_count=result.failed_count,
        total_processed=result.total_processed,
        row_results=[
            {
                "row_number": row.row_number,
                "status": row.status.value,
                "reason_code": row.reason_code,
                "values": row.values,
            }
            for row in result.rows
        ],
    )


@router.get("/template.csv")
def download_customer_import_template_csv(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)
    organization = _organization_or_404(db, organization_id)

    labels, example_row = build_template_labels_and_example(organization)
    content = build_csv_template(labels, example_row)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="customers-template.csv"'},
    )


@router.get("/template.xlsx")
def download_customer_import_template_xlsx(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)
    organization = _organization_or_404(db, organization_id)

    labels, example_row = build_template_labels_and_example(organization)
    content = build_xlsx_template(labels, example_row)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="customers-template.xlsx"'},
    )
