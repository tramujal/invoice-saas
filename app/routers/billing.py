"""Tenant-facing billing routes:
- GET /organizations/{organization_id}/subscription -- read-only view of
  an organization's own subscription: status, billing period, trial
  dates, current period, cancel_at_period_end, its plan, and the
  resolved capability layer (app.billing.capabilities) so the frontend
  never has to re-derive "can I create another X" from raw limits/usage
  itself.
- POST .../billing/checkout -- starts a hosted checkout session (Phase
  18/19) to move onto a different plan/billing period.
- POST .../billing/portal -- starts a hosted billing-management session
  (Phase 19) for an organization that already has a provider customer on
  file.

Platform-admin subscription endpoints (list/detail/change-plan/cancel/
reactivate/resume) live in app.routers.platform_admin instead, alongside
every other admin-surface route, not here -- see that module's own
subscriptions section.

GET .../subscription still never exposes provider_name/provider_reference
(see Subscription's own docstring in app.models) -- those are internal
implementation details (which provider, which of its own ids), not
something the frontend needs to render a subscription's own state.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.capabilities import (
    can_create_api_key,
    can_create_invoice,
    can_create_quote,
    can_create_webhook,
    can_use_ai,
    can_use_analytics,
    can_use_background_jobs,
    can_use_forecasting,
    get_organization_capabilities,
    remaining_api_keys,
    remaining_invoice_quota,
    remaining_quote_quota,
    remaining_users,
    remaining_webhooks,
)
from app.billing.provider_base import (
    BillingProvider,
    BillingProviderError,
    BillingProviderNotConfiguredError,
)
from app.billing.service import BillingService
from app.billing_period import BillingPeriod
from app.database import get_db
from app.deps import (
    get_billing_provider_dependency,
    get_current_user,
    require_org_member,
    require_permission,
    require_verified_email,
)
from app.models import Plan, User
from app.permissions import Permission
from app.schemas import (
    CapabilitiesResponse,
    PlanFeatures,
    PlanLimits,
    PlanResponse,
    StartCheckoutRequest,
    StartCheckoutResponse,
    StartPortalSessionRequest,
    StartPortalSessionResponse,
    SubscriptionResponse,
)
from app.services.entitlements import get_active_subscription

router = APIRouter(prefix="/organizations/{organization_id}", tags=["billing"])


def _build_plan_response(plan: Plan) -> PlanResponse:
    return PlanResponse(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        description=plan.description,
        is_active=plan.is_active,
        is_default=plan.is_default,
        sort_order=plan.sort_order,
        public=plan.public,
        monthly_price=plan.monthly_price,
        yearly_price=plan.yearly_price,
        currency=plan.currency,
        limits=PlanLimits(
            max_users=plan.max_users,
            max_customers=plan.max_customers,
            max_products=plan.max_products,
            max_invoices_per_month=plan.max_invoices_per_month,
            max_quotes_per_month=plan.max_quotes_per_month,
            max_ai_actions_per_month=plan.max_ai_actions_per_month,
            storage_limit_mb=plan.storage_limit_mb,
            max_api_keys=plan.max_api_keys,
            max_webhooks=plan.max_webhooks,
        ),
        features=PlanFeatures(
            custom_branding_enabled=plan.custom_branding_enabled,
            api_access_enabled=plan.api_access_enabled,
            advanced_reports_enabled=plan.advanced_reports_enabled,
            analytics_enabled=plan.analytics_enabled,
            forecasting_enabled=plan.forecasting_enabled,
            ai_enabled=plan.ai_enabled,
            background_jobs_enabled=plan.background_jobs_enabled,
        ),
        version=plan.version,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@router.get("/billing/plans", response_model=list[PlanResponse])
def list_public_plans(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PlanResponse]:
    """The plan catalog a tenant chooses from when starting a checkout
    (Phase 19) -- every active, public plan (see Plan.public's own
    docstring: public=False marks a legacy plan kept only for its
    existing subscribers, never newly offered). Not organization-
    specific data -- `organization_id` in the path is only used for the
    same require_org_member gate every route in this router uses, so a
    stranger can't enumerate plan pricing through an org they don't
    belong to; the plan list returned is identical for every org."""
    require_org_member(current_user, organization_id, db)
    plans = db.scalars(
        select(Plan)
        .where(Plan.is_active.is_(True), Plan.public.is_(True))
        .order_by(Plan.sort_order)
    ).all()
    return [_build_plan_response(plan) for plan in plans]


@router.get("/subscription", response_model=SubscriptionResponse)
def get_organization_subscription(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubscriptionResponse:
    # Same low-sensitivity, "every member already implicitly needs this"
    # gate as GET .../entitlements and GET .../usage -- knowing your own
    # organization's plan/trial status isn't a permission-gated action.
    require_org_member(current_user, organization_id, db)

    subscription = get_active_subscription(db, organization_id)
    plan = db.get(Plan, subscription.plan_id)
    caps = get_organization_capabilities(db, organization_id)

    return SubscriptionResponse(
        id=subscription.id,
        organization_id=subscription.organization_id,
        plan=_build_plan_response(plan),
        status=subscription.status,
        billing_period=subscription.billing_period,
        trial_start=subscription.trial_start,
        trial_end=subscription.trial_end,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        canceled_at=subscription.canceled_at,
        ended_at=subscription.ended_at,
        capabilities=CapabilitiesResponse(
            can_use_ai=can_use_ai(caps),
            can_use_analytics=can_use_analytics(caps),
            can_use_forecasting=can_use_forecasting(caps),
            can_use_background_jobs=can_use_background_jobs(caps),
            can_create_invoice=can_create_invoice(caps),
            can_create_quote=can_create_quote(caps),
            can_create_api_key=can_create_api_key(caps),
            can_create_webhook=can_create_webhook(caps),
            remaining_invoice_quota=remaining_invoice_quota(caps),
            remaining_quote_quota=remaining_quote_quota(caps),
            remaining_users=remaining_users(caps),
            remaining_api_keys=remaining_api_keys(caps),
            remaining_webhooks=remaining_webhooks(caps),
        ),
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


@router.post("/billing/checkout", response_model=StartCheckoutResponse)
def start_organization_checkout(
    organization_id: str,
    body: StartCheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: BillingProvider = Depends(get_billing_provider_dependency),
) -> StartCheckoutResponse:
    """Starts a hosted checkout session for moving this organization onto
    `body.plan_id`/`body.billing_period` -- the first tenant-initiated
    (as opposed to platform-admin-initiated) plan-change entry point in
    this app. Gated by Permission.billing_manage (owner-only, reserved
    for exactly this since Phase 13B's permission map) -- see
    app.permissions.Permission's own inline comment on that value.

    Never mutates the organization's Subscription itself -- see
    BillingService.start_checkout's own docstring on why that only
    happens once a checkout_completed webhook event arrives via
    app.routers.billing_webhooks."""
    require_permission(current_user, organization_id, Permission.billing_manage, db)
    require_verified_email(current_user)

    try:
        billing_period = BillingPeriod(body.billing_period)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid billing_period {body.billing_period!r}. Expected 'monthly' or 'yearly'.",
        )

    plan = db.get(Plan, body.plan_id)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    subscription = get_active_subscription(db, organization_id)

    try:
        session = BillingService(db, provider=provider).start_checkout(
            subscription,
            plan,
            billing_period,
            actor=current_user,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    except BillingProviderNotConfiguredError as exc:
        # NullBillingProvider (the default when BILLING_PROVIDER is
        # unset) only raises this the moment a method is actually called
        # -- get_billing_provider_dependency's own 503 mapping only
        # catches the "explicitly selected an unconfigured provider"
        # case at resolution time, so this is the second place the same
        # "not configured" condition can surface.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "billing_provider_not_configured", "message": str(exc)},
        ) from exc
    except BillingProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not start checkout: {exc}"
        ) from exc

    return StartCheckoutResponse(checkout_url=session.url)


@router.post("/billing/portal", response_model=StartPortalSessionResponse)
def start_organization_portal_session(
    organization_id: str,
    body: StartPortalSessionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: BillingProvider = Depends(get_billing_provider_dependency),
) -> StartPortalSessionResponse:
    """Starts a hosted billing-management session for this organization --
    same gating as .../billing/checkout (Permission.billing_manage +
    verified email). Requires the organization to already have a
    provider customer on file (app.models.ProviderCustomer, created the
    first time it starts a checkout) -- returns 404 if it doesn't, since
    there's nothing to manage on the provider's side yet."""
    require_permission(current_user, organization_id, Permission.billing_manage, db)
    require_verified_email(current_user)

    subscription = get_active_subscription(db, organization_id)

    try:
        session = BillingService(db, provider=provider).start_portal_session(
            subscription, return_url=body.return_url
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BillingProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "billing_provider_not_configured", "message": str(exc)},
        ) from exc
    except BillingProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not start portal session: {exc}"
        ) from exc

    return StartPortalSessionResponse(portal_url=session.url)
