"""Phase 17B -- the raising layer for FEATURE-FLAGGED (not quota-based)
capabilities: AI and analytics. Mirrors app.services.plan_limits' own
"pure computation stays in capabilities.py, this module just adds the
raise" split, for the two capabilities that are all-or-nothing booleans
rather than a used-vs-limit quota (those go through plan_limits.check_limit
instead -- see that module's own docstring).

Forecasting (can_use_forecasting) and background jobs
(can_use_background_jobs) are deliberately NOT raising checks here:
- Forecasting degrades softly (app.routers.analytics.get_trend_snapshot
  returns an ordinary, structurally-valid ForecastResponse with
  available=False, plan_restricted=True instead of rejecting the whole
  request -- a plan without forecasting still gets its trend/comparison
  data, matching Starter's own capability matrix, which has analytics
  without forecasting).
- Background jobs gate silently, with no user-facing request to reject
  at all: app.services.webhook_events.record_webhook_event always
  records the WebhookEvent (immutable history) but only enqueues
  WebhookDelivery rows when can_use_background_jobs is true -- there is
  no router call site to raise from, since no one but the system enqueues
  a delivery.
"""

from sqlalchemy.orm import Session

from app.billing.capabilities import (
    OrganizationCapabilities,
    can_use_ai,
    can_use_analytics,
    get_organization_capabilities,
)


class CapabilityDeniedError(Exception):
    """Raised when a request needs a plan feature (not a quota) the
    organization's current plan doesn't include. Carries everything the
    403 feature_not_available response needs (see to_error_detail) --
    routers never rebuild this from scratch, matching
    PlanLimitExceededError's own precedent for the 409 quota case."""

    def __init__(self, *, feature: str, plan_id: str, plan_code: str, plan_name: str) -> None:
        super().__init__(f"{feature!r} is not available on plan {plan_code!r}")
        self.feature = feature
        self.plan_id = plan_id
        self.plan_code = plan_code
        self.plan_name = plan_name

    def to_error_detail(self) -> dict:
        return {
            "code": "feature_not_available",
            "feature": self.feature,
            "plan": {"id": self.plan_id, "code": self.plan_code, "name": self.plan_name},
            "message": (
                f"{self.feature.replace('_', ' ').title()} is not included in your "
                f"{self.plan_name} plan."
            ),
        }


def _require(caps: OrganizationCapabilities, *, feature: str, allowed: bool) -> OrganizationCapabilities:
    if not allowed:
        raise CapabilityDeniedError(
            feature=feature,
            plan_id=caps.entitlements.plan_id,
            plan_code=caps.entitlements.plan_code,
            plan_name=caps.entitlements.plan_name,
        )
    return caps


def require_ai(db: Session, organization_id: str) -> OrganizationCapabilities:
    """Raises CapabilityDeniedError if the organization's plan doesn't
    include AI at all -- checked in addition to (and before) the existing
    monthly ai_actions quota (app.services.plan_limits.LimitedResource
    .ai_actions), which still applies on top of this for plans that do
    have AI enabled."""
    caps = get_organization_capabilities(db, organization_id)
    return _require(caps, feature="ai", allowed=can_use_ai(caps))


def require_analytics(db: Session, organization_id: str) -> OrganizationCapabilities:
    """Raises CapabilityDeniedError if the organization's plan doesn't
    include the Analytics domain (the dedicated /analytics/kpis and
    /analytics/trends endpoints -- never the core /dashboard endpoint,
    which predates Phase 16A's paid Analytics surface and stays available
    to every plan)."""
    caps = get_organization_capabilities(db, organization_id)
    return _require(caps, feature="analytics", allowed=can_use_analytics(caps))
