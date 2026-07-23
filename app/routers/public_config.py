"""A single, unauthenticated, minimal-by-design endpoint for the public
login/register UI to check before rendering -- never a general-purpose
public settings surface. See app.schemas.PublicConfigResponse's own
docstring for exactly which two fields this returns and why nothing else
belongs here (no internal readiness, no feature-provider configuration,
no admin-only setting)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import PublicConfigResponse
from app.services.platform_settings import get_effective_settings

router = APIRouter(prefix="/public", tags=["public_config"])


@router.get("/config", response_model=PublicConfigResponse)
def get_public_config(db: Session = Depends(get_db)) -> PublicConfigResponse:
    settings = get_effective_settings(db)
    return PublicConfigResponse(
        maintenance_mode=settings.maintenance_mode,
        registrations_enabled=settings.registrations_enabled,
    )
