"""Tenant-facing, self-scoped notification routes:
- GET /organizations/{organization_id}/notifications -- the current
  user's own in-app inbox for this organization, paginated, optionally
  filtered to unread only.
- POST .../notifications/{notification_id}/read -- marks one of the
  current user's own notifications read.
- POST .../notifications/read-all -- marks every unread notification of
  the current user's, in this organization, read in one call.
- GET/PATCH .../notification-preferences -- the current user's own
  email-notification opt-out for this organization (see
  app.notifications.service.is_email_enabled/set_email_enabled).

Every route here is scoped to `current_user`'s own rows only (never
another member's) -- membership in the organization (require_org_member)
is the only gate; there is no separate Permission needed, since a
member's own inbox/preferences are never a privileged view of someone
else's data.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member
from app.models import Notification, User
from app.notifications.service import is_email_enabled, set_email_enabled
from app.schemas import (
    NotificationPreferenceResponse,
    NotificationResponse,
    PaginatedNotificationsResponse,
    UpdateNotificationPreferenceRequest,
)

router = APIRouter(prefix="/organizations/{organization_id}", tags=["notifications"])


def _paginated_notifications(
    db: Session,
    *,
    organization_id: str,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    unread_only: bool = False,
) -> PaginatedNotificationsResponse:
    """Plain function (no FastAPI Query defaults) so it can be called
    directly from Python -- both the GET endpoint below and
    mark_all_notifications_read (which needs the same shape as its own
    response) share this rather than one calling the other's route
    handler, whose `limit`/`offset`/`unread_only` parameters are
    FastAPI Query objects only resolved by the framework's own request
    handling, never by a direct Python call."""
    base_query = select(Notification).where(
        Notification.organization_id == organization_id,
        Notification.user_id == user_id,
    )
    if unread_only:
        base_query = base_query.where(Notification.read_at.is_(None))

    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    unread_count = (
        db.scalar(
            select(func.count()).select_from(
                select(Notification)
                .where(
                    Notification.organization_id == organization_id,
                    Notification.user_id == user_id,
                    Notification.read_at.is_(None),
                )
                .subquery()
            )
        )
        or 0
    )
    items = db.scalars(
        base_query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    ).all()

    return PaginatedNotificationsResponse(
        total=total,
        unread_count=unread_count,
        items=[NotificationResponse.model_validate(item) for item in items],
    )


@router.get("/notifications", response_model=PaginatedNotificationsResponse)
def list_notifications(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = Query(default=False),
) -> PaginatedNotificationsResponse:
    require_org_member(current_user, organization_id, db)
    return _paginated_notifications(
        db,
        organization_id=organization_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )


def _owned_notification_or_404(db: Session, *, organization_id: str, notification_id: str, user_id: str) -> Notification:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.organization_id == organization_id,
            Notification.user_id == user_id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notification


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    organization_id: str,
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationResponse:
    require_org_member(current_user, organization_id, db)
    notification = _owned_notification_or_404(
        db, organization_id=organization_id, notification_id=notification_id, user_id=current_user.id
    )
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return NotificationResponse.model_validate(notification)


@router.post("/notifications/read-all", response_model=PaginatedNotificationsResponse)
def mark_all_notifications_read(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedNotificationsResponse:
    require_org_member(current_user, organization_id, db)
    unread = db.scalars(
        select(Notification).where(
            Notification.organization_id == organization_id,
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None),
        )
    ).all()
    now = datetime.now(timezone.utc)
    for notification in unread:
        notification.read_at = now
    db.commit()

    return _paginated_notifications(db, organization_id=organization_id, user_id=current_user.id)


@router.get("/notification-preferences", response_model=NotificationPreferenceResponse)
def get_notification_preferences(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationPreferenceResponse:
    require_org_member(current_user, organization_id, db)
    return NotificationPreferenceResponse(
        email_enabled=is_email_enabled(db, user_id=current_user.id, organization_id=organization_id)
    )


@router.patch("/notification-preferences", response_model=NotificationPreferenceResponse)
def update_notification_preferences(
    organization_id: str,
    body: UpdateNotificationPreferenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationPreferenceResponse:
    require_org_member(current_user, organization_id, db)
    set_email_enabled(
        db, user_id=current_user.id, organization_id=organization_id, enabled=body.email_enabled
    )
    db.commit()
    return NotificationPreferenceResponse(email_enabled=body.email_enabled)
