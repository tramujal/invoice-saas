from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member, require_permission, require_verified_email
from app.models import Organization, User
from app.permissions import Permission
from app.reminder_settings import format_day_list
from app.schemas import OrganizationProfileResponse, OrganizationUpdateRequest

# The ORM columns for these two are comma-separated strings (see
# app.reminder_settings), but the API's wire shape for them is a plain
# JSON array of ints -- these need converting before the generic setattr
# loop below, unlike every other field on this request.
_DAY_LIST_FIELDS = {
    "reminder_before_due_days",
    "reminder_after_due_days",
    "quote_reminder_before_expiry_days",
}

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
    # Deliberately left on require_org_member, not migrated to
    # require_permission -- there is no requested "organization.read"
    # permission, and the org profile is low-sensitivity info every
    # member already implicitly needs (name, currency, localization, etc).
    require_org_member(current_user, organization_id, db)
    return _organization_or_404(db, organization_id)


@router.patch("", response_model=OrganizationProfileResponse)
def update_organization(
    organization_id: str,
    body: OrganizationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    require_permission(current_user, organization_id, Permission.settings_manage, db)
    require_verified_email(current_user)
    organization = _organization_or_404(db, organization_id)
    # mode="json" ensures enum fields (language/currency_code/tax_label) are
    # written as their plain string .value rather than the Enum member
    # itself, matching how every other field on this model is persisted.
    for key, value in body.model_dump(exclude_unset=True, mode="json").items():
        if key in _DAY_LIST_FIELDS:
            value = format_day_list(value)
        setattr(organization, key, value)
    db.commit()
    db.refresh(organization)
    return organization
