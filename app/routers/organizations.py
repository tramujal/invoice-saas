from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_org_member, require_permission, require_verified_email
from app.models import Organization, User
from app.permissions import Permission
from app.reminder_settings import format_day_list
from app.schemas import (
    OrganizationEntitlementsResponse,
    OrganizationProfileResponse,
    OrganizationUpdateRequest,
    PlanFeatures,
    PlanLimits,
)
from app.services.entitlements import get_organization_entitlements

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


@router.get("/entitlements", response_model=OrganizationEntitlementsResponse)
def get_organization_entitlements_endpoint(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrganizationEntitlementsResponse:
    """Read-only view of what this organization's current plan allows --
    same low-sensitivity, "every member already implicitly needs this"
    gate as GET /organizations/{id} above (require_org_member only, no
    specific Permission). Every value here comes from
    app.services.entitlements.get_organization_entitlements -- this
    router never reads app.models.Plan columns directly."""
    require_org_member(current_user, organization_id, db)
    _organization_or_404(db, organization_id)
    entitlements = get_organization_entitlements(db, organization_id)
    return OrganizationEntitlementsResponse(
        plan_id=entitlements.plan_id,
        plan_code=entitlements.plan_code,
        plan_name=entitlements.plan_name,
        limits=PlanLimits(
            max_users=entitlements.max_users,
            max_customers=entitlements.max_customers,
            max_products=entitlements.max_products,
            max_invoices_per_month=entitlements.max_invoices_per_month,
            max_quotes_per_month=entitlements.max_quotes_per_month,
            max_ai_actions_per_month=entitlements.max_ai_actions_per_month,
            storage_limit_mb=entitlements.storage_limit_mb,
        ),
        features=PlanFeatures(
            custom_branding_enabled=entitlements.custom_branding_enabled,
            api_access_enabled=entitlements.api_access_enabled,
            advanced_reports_enabled=entitlements.advanced_reports_enabled,
        ),
    )


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
