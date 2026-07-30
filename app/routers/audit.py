"""Tenant-facing, organization-scoped audit timeline:
GET /organizations/{organization_id}/audit-entries -- paginated, filtered
by actor, event type, resource type, resource id, and date range. Reads
only (see app.audit.queries.list_audit_entries); AuditEntry rows are
never created, updated, or deleted through this router -- they are
written exclusively from inside app.notifications.service.emit_event's
own fan-out (see app.audit.service.record_audit_entry).

Gated by Permission.audit_view (granted to admin+owner, mirroring
settings.manage's sensitivity level -- an audit trail can reveal who
deleted/changed what, so it is not exposed to every member by default).
"""

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.queries import list_audit_entries
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import AuditEntry, User
from app.permissions import Permission
from app.schemas import AuditEntryResponse, PaginatedAuditEntriesResponse

router = APIRouter(prefix="/organizations/{organization_id}", tags=["audit"])


def _actor_emails(db: Session, entries: list[AuditEntry]) -> dict[str, str]:
    """One batch lookup for every distinct actor_user_id on this page --
    never N+1 queries. An actor whose account was since deleted (or any
    id not found) is simply absent from the returned map, which
    _entry_response treats as "no email to show," never an error."""
    actor_ids = {entry.actor_user_id for entry in entries if entry.actor_user_id is not None}
    if not actor_ids:
        return {}
    rows = db.execute(select(User.id, User.email).where(User.id.in_(actor_ids))).all()
    return {user_id: email for user_id, email in rows}


def _entry_response(entry: AuditEntry, actor_emails: dict[str, str]) -> AuditEntryResponse:
    return AuditEntryResponse(
        id=entry.id,
        organization_id=entry.organization_id,
        actor_user_id=entry.actor_user_id,
        actor_email=actor_emails.get(entry.actor_user_id) if entry.actor_user_id else None,
        event_type=entry.event_type,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        metadata=json.loads(entry.metadata_json) if entry.metadata_json else None,
        created_at=entry.created_at,
    )


@router.get("/audit-entries", response_model=PaginatedAuditEntriesResponse)
def list_organization_audit_entries(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor_user_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> PaginatedAuditEntriesResponse:
    require_permission(current_user, organization_id, Permission.audit_view, db)

    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_date_range", "message": "date_from must not be after date_to."},
        )

    page = list_audit_entries(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    actor_emails = _actor_emails(db, page.items)
    return PaginatedAuditEntriesResponse(
        total=page.total, items=[_entry_response(entry, actor_emails) for entry in page.items]
    )
