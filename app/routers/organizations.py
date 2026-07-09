from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member
from app.models import Organization, User
from app.schemas import OrganizationProfileResponse, OrganizationUpdateRequest

router = APIRouter(prefix="/organizations/{organization_id}", tags=["organizations"])


def _organization_or_404(db: Session, organization_id: str) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return organization


@router.get("", response_model=OrganizationProfileResponse)
def get_organization(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    require_org_member(current_user, organization_id, db)
    return _organization_or_404(db, organization_id)


@router.patch("", response_model=OrganizationProfileResponse)
def update_organization(
    organization_id: str,
    body: OrganizationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    require_org_member(current_user, organization_id, db)
    organization = _organization_or_404(db, organization_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(organization, key, value)
    db.commit()
    db.refresh(organization)
    return organization
