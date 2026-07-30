"""list_audit_entries -- the one read path for AuditEntry rows, filtered
and paginated for app.routers.audit's GET /organizations/{id}/audit-entries
endpoint. Mirrors app.routers.platform_admin.list_platform_audit_log's own
filter-building/pagination shape (same date-range-inclusive-of-end-date
convention), scoped down to a single organization instead of platform-wide.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEntry


@dataclass(frozen=True)
class AuditEntryPage:
    total: int
    items: list[AuditEntry]


def list_audit_entries(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str | None = None,
    event_type: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> AuditEntryPage:
    base_query = select(AuditEntry).where(AuditEntry.organization_id == organization_id)

    if actor_user_id:
        base_query = base_query.where(AuditEntry.actor_user_id == actor_user_id)
    if event_type:
        base_query = base_query.where(AuditEntry.event_type == event_type)
    if resource_type:
        base_query = base_query.where(AuditEntry.resource_type == resource_type)
    if resource_id:
        base_query = base_query.where(AuditEntry.resource_id == resource_id)
    if date_from is not None:
        base_query = base_query.where(AuditEntry.created_at >= date_from)
    if date_to is not None:
        # Inclusive of the entire end date, not just its midnight instant --
        # matches list_platform_audit_log's identical convention.
        base_query = base_query.where(AuditEntry.created_at < date_to + timedelta(days=1))

    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0

    rows = db.scalars(
        base_query.order_by(AuditEntry.created_at.desc(), AuditEntry.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return AuditEntryPage(total=total, items=list(rows))
