from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.service import AnalyticsService
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import User
from app.permissions import Permission
from app.schemas import DashboardAnalyticsResponse, DashboardResponse

router = APIRouter(
    prefix="/organizations/{organization_id}/dashboard", tags=["dashboard"]
)


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    require_permission(current_user, organization_id, Permission.dashboard_view, db)
    return AnalyticsService(db, organization_id).dashboard_summary()


@router.get("/analytics", response_model=DashboardAnalyticsResponse)
def get_dashboard_analytics(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardAnalyticsResponse:
    require_permission(current_user, organization_id, Permission.dashboard_view, db)
    return AnalyticsService(db, organization_id).dashboard_analytics()
