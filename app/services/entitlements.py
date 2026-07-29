"""The single centralized place that reads app.models.Plan columns.

Phase 14A defines commercial plans and what an organization is entitled
to -- it deliberately does NOT implement usage tracking or limit
enforcement (later phases). This module is still built as the one
resolution point every future enforcement check will go through, so no
router or service ever has to read Plan columns directly, compare a
limit, or check a feature flag itself: they call get_organization_
entitlements() and then feature_enabled()/get_limit() on the result.

NULL = unlimited, 0 = unavailable, positive integer = hard limit for
every numeric limit (see Plan's own docstring) -- get_limit() returns
that raw value unchanged; callers decide how to render/enforce it.

Phase 17A change: entitlements now resolve through the organization's
Subscription -> Plan (see get_active_subscription below), never through
Organization.plan_id directly -- Subscription is the source of truth
from this phase onward (see app.models.Subscription's own docstring).
Organization.plan_id still exists as a deprecated, unread denormalized
column; nothing in this module touches it anymore.
"""

from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, Plan, Subscription


class PlanNotFoundError(Exception):
    """Raised when a subscription's plan_id no longer resolves to a
    Plan row -- should be unreachable in practice (plans are never
    deleted, only deactivated; see Plan's own docstring), but callers
    fail closed rather than crash with an unhandled AttributeError."""


class NoDefaultPlanError(Exception):
    """Raised when get_default_plan() finds no plan with is_default=True
    -- should be unreachable given the "exactly one active default plan"
    invariant enforced by POST /admin/plans/{id}/make-default, but
    resolving a default plan fails closed rather than silently picking
    an arbitrary one."""


class NoActiveSubscriptionError(Exception):
    """Raised when an organization has no Subscription row at all --
    should be unreachable given every organization gets one at
    registration (app.billing.service.BillingService.create_subscription)
    or via the Phase 17A migration backfill for pre-existing
    organizations, but resolution fails closed rather than crashing with
    an unhandled AttributeError."""


class PlanFeature(str, Enum):
    """The commercial feature entitlements this app defines. Values are
    the exact Plan column names, so feature_enabled() can resolve them
    with a plain getattr -- see that function. The last four were added
    in Phase 17A alongside the billing/subscription domain."""

    custom_branding = "custom_branding_enabled"
    api_access = "api_access_enabled"
    advanced_reports = "advanced_reports_enabled"
    analytics = "analytics_enabled"
    forecasting = "forecasting_enabled"
    ai = "ai_enabled"
    background_jobs = "background_jobs_enabled"


class PlanLimit(str, Enum):
    """The numeric limits this app defines. Values are the exact Plan
    column names, for the same reason as PlanFeature above. The last two
    were added in Phase 17A."""

    max_users = "max_users"
    max_customers = "max_customers"
    max_products = "max_products"
    max_invoices_per_month = "max_invoices_per_month"
    max_quotes_per_month = "max_quotes_per_month"
    max_ai_actions_per_month = "max_ai_actions_per_month"
    storage_limit_mb = "storage_limit_mb"
    max_api_keys = "max_api_keys"
    max_webhooks = "max_webhooks"


@dataclass(frozen=True)
class Entitlements:
    """An organization's resolved, point-in-time commercial entitlements
    -- a plain snapshot, not a live ORM object, so a caller can't
    accidentally mutate a Plan row through it. Includes the plan's own
    identity (id/code/name) since every consumer of this (the org-facing
    entitlements endpoint, the platform admin UI) needs to say *which*
    plan these limits/features came from."""

    plan_id: str
    plan_code: str
    plan_name: str
    max_users: int | None
    max_customers: int | None
    max_products: int | None
    max_invoices_per_month: int | None
    max_quotes_per_month: int | None
    max_ai_actions_per_month: int | None
    storage_limit_mb: int | None
    max_api_keys: int | None
    max_webhooks: int | None
    custom_branding_enabled: bool
    api_access_enabled: bool
    advanced_reports_enabled: bool
    analytics_enabled: bool
    forecasting_enabled: bool
    ai_enabled: bool
    background_jobs_enabled: bool


def _entitlements_from_plan(plan: Plan) -> Entitlements:
    return Entitlements(
        plan_id=plan.id,
        plan_code=plan.code,
        plan_name=plan.name,
        max_users=plan.max_users,
        max_customers=plan.max_customers,
        max_products=plan.max_products,
        max_invoices_per_month=plan.max_invoices_per_month,
        max_quotes_per_month=plan.max_quotes_per_month,
        max_ai_actions_per_month=plan.max_ai_actions_per_month,
        storage_limit_mb=plan.storage_limit_mb,
        max_api_keys=plan.max_api_keys,
        max_webhooks=plan.max_webhooks,
        custom_branding_enabled=plan.custom_branding_enabled,
        api_access_enabled=plan.api_access_enabled,
        advanced_reports_enabled=plan.advanced_reports_enabled,
        analytics_enabled=plan.analytics_enabled,
        forecasting_enabled=plan.forecasting_enabled,
        ai_enabled=plan.ai_enabled,
        background_jobs_enabled=plan.background_jobs_enabled,
    )


def get_active_subscription(db: Session, organization_id: str) -> Subscription:
    """Returns the organization's one Subscription row -- the resolved
    source of truth for its plan from Phase 17A onward (see
    app.models.Subscription's own docstring). Every organization has
    exactly one (unique constraint on Subscription.organization_id),
    populated at registration or by the Phase 17A migration backfill for
    pre-existing organizations -- a missing row is an unreachable state,
    not a normal "not subscribed yet" condition (there is no such thing
    in this app; even the Free plan is a real subscription)."""
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise LookupError(f"Organization {organization_id!r} not found")
    subscription = db.scalar(
        select(Subscription).where(Subscription.organization_id == organization_id)
    )
    if subscription is None:
        raise NoActiveSubscriptionError(
            f"Organization {organization_id!r} has no subscription"
        )
    return subscription


def get_organization_plan(db: Session, organization_id: str) -> Plan:
    """Returns the live Plan row currently assigned to organization_id,
    resolved via its Subscription (see get_active_subscription above).
    Callers that only need to resolve entitlements (limits/features)
    should use get_organization_entitlements() instead -- this is for
    callers that need the plan's own mutable identity (e.g. the platform
    admin org-detail response, which shows the plan's name/code)."""
    subscription = get_active_subscription(db, organization_id)
    plan = db.get(Plan, subscription.plan_id)
    if plan is None:
        raise PlanNotFoundError(
            f"Organization {organization_id!r}'s subscription plan_id "
            f"{subscription.plan_id!r} does not exist"
        )
    return plan


def get_organization_entitlements(db: Session, organization_id: str) -> Entitlements:
    """The one function every enforcement/display point in this app
    should call to find out what an organization is entitled to."""
    return _entitlements_from_plan(get_organization_plan(db, organization_id))


def feature_enabled(entitlements: Entitlements, feature: PlanFeature) -> bool:
    return bool(getattr(entitlements, feature.value))


def get_limit(entitlements: Entitlements, limit: PlanLimit) -> int | None:
    """None means unlimited, 0 means unavailable, a positive integer is
    a hard limit -- see this module's own docstring. Returned exactly as
    stored; no interpretation happens here."""
    return getattr(entitlements, limit.value)


def get_default_plan(db: Session) -> Plan:
    """Resolves the current active default plan -- used at organization
    creation (app.routers.auth.register) so a future change to which
    plan is default (via POST /admin/plans/{id}/make-default) is honored
    by new signups immediately, without ever hardcoding a plan id/code
    outside this module."""
    plan = db.scalar(select(Plan).where(Plan.is_default.is_(True)))
    if plan is None:
        raise NoDefaultPlanError("No plan is currently marked as the default")
    return plan
