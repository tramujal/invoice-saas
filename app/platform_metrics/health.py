"""System health aggregates that extend, rather than duplicate,
app.routers.platform_admin's existing `_system_health` -- see that
function for the single GET /admin/system/health endpoint every one of
these values feeds into. Nothing here is a second health-reporting
surface.
"""

from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.job_status import JobStatus
from app.models import BackgroundJob


@dataclass(frozen=True)
class QueueStatus:
    pending: int
    running: int
    retry_scheduled: int
    failed_total: int
    succeeded_total: int


def queue_status(db: Session) -> QueueStatus:
    rows = db.execute(select(BackgroundJob.status, func.count()).group_by(BackgroundJob.status)).all()
    by_status = dict(rows)
    return QueueStatus(
        pending=by_status.get(JobStatus.pending.value, 0),
        running=by_status.get(JobStatus.claimed.value, 0) + by_status.get(JobStatus.running.value, 0),
        retry_scheduled=by_status.get(JobStatus.retry_scheduled.value, 0),
        failed_total=by_status.get(JobStatus.permanently_failed.value, 0),
        succeeded_total=by_status.get(JobStatus.succeeded.value, 0),
    )


def storage_used_mb() -> int:
    """Always 0 -- mirrors app.services.organization_usage.count_storage's
    own honest reasoning verbatim: this app has no file-upload/storage
    subsystem at all today. Revisit the moment a real storage feature
    exists; a fabricated non-zero number here would violate "single
    source of truth" for a fact that doesn't exist yet."""
    return 0


def database_size_mb(db: Session) -> float | None:
    """Best-effort, dialect-aware DB size introspection -- a single
    read-only query, never a write, never a new persisted table. Returns
    None (rather than 0, which would be a false "empty database" claim)
    if the introspection query itself fails for any reason (restricted
    permissions, an unsupported dialect) -- an honest "unknown," not a
    fabricated number."""
    dialect = db.bind.dialect.name if db.bind is not None else ""
    try:
        if dialect == "postgresql":
            size_bytes = db.scalar(text("SELECT pg_database_size(current_database())"))
        elif dialect == "sqlite":
            page_count = db.scalar(text("PRAGMA page_count"))
            page_size = db.scalar(text("PRAGMA page_size"))
            size_bytes = (page_count or 0) * (page_size or 0)
        else:
            return None
    except Exception:
        return None
    if size_bytes is None:
        return None
    return round(size_bytes / (1024 * 1024), 2)
