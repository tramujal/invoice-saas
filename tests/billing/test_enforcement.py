"""Phase 17B -- capability enforcement wired into real feature entry
points: AI (app.routers.assistant), Analytics/Forecasting
(app.routers.analytics), API keys/webhooks (app.services
.organization_api_keys/webhook_endpoints, via app.services.plan_limits),
and background jobs (app.services.webhook_events). Complements
tests/billing/test_capabilities.py (pure capability-layer logic) and
tests/test_plan_limits.py (the quota-check mechanism itself, unchanged
externally by this phase's refactor) -- this file is specifically about
the *new* denial paths those two don't cover: a Free-tier organization
(every one of these capabilities disabled/zero by default) actually
getting blocked, and an entitled plan being unaffected.
"""

from app.billing.capabilities import (
    can_create_customer,
    can_create_product,
    get_organization_capabilities,
    remaining_ai_actions_quota,
    remaining_customers,
    remaining_products,
)
from app.billing.enforcement import CapabilityDeniedError, require_ai, require_analytics
from app.models import WebhookDelivery, WebhookEvent
from app.services.plan_limits import LimitedResource, PlanLimitExceededError, check_limit
from app.services.webhook_endpoints import create_endpoint
from app.services.webhook_events import record_webhook_event
from app.webhook_event_type import WebhookEventType
from tests.factories import make_customer, make_org_with_owner, make_org_with_owner_on_plan


# --- app.billing.capabilities: new quota functions (Phase 17B) --------------


def test_remaining_customers_and_products_reflect_plan_and_usage(db_session):
    owner = make_org_with_owner_on_plan(db_session, max_customers=2, max_products=0)
    make_customer(db_session, owner.organization)
    caps = get_organization_capabilities(db_session, owner.organization.id)

    assert remaining_customers(caps) == 1
    assert can_create_customer(caps) is True
    assert remaining_products(caps) == 0
    assert can_create_product(caps) is False


def test_remaining_ai_actions_quota_matches_plan_limit(db_session):
    owner = make_org_with_owner_on_plan(db_session, max_ai_actions_per_month=5)
    caps = get_organization_capabilities(db_session, owner.organization.id)
    assert remaining_ai_actions_quota(caps) == 5


# --- app.billing.enforcement: raising helpers --------------------------------


def test_require_ai_raises_for_a_plan_without_ai(db_session):
    owner = make_org_with_owner(db_session, email="require-ai-denied@example.com")
    try:
        require_ai(db_session, owner.organization.id)
        assert False, "expected CapabilityDeniedError"
    except CapabilityDeniedError as exc:
        detail = exc.to_error_detail()
        assert detail["code"] == "feature_not_available"
        assert detail["feature"] == "ai"
        assert detail["plan"]["code"] == "free"


def test_require_ai_is_a_noop_for_a_plan_with_ai(db_session):
    owner = make_org_with_owner_on_plan(db_session, email="require-ai-ok@example.com", ai_enabled=True)
    caps = require_ai(db_session, owner.organization.id)
    assert caps.entitlements.ai_enabled is True


def test_require_analytics_raises_for_a_plan_without_analytics(db_session):
    owner = make_org_with_owner(db_session, email="require-analytics-denied@example.com")
    try:
        require_analytics(db_session, owner.organization.id)
        assert False, "expected CapabilityDeniedError"
    except CapabilityDeniedError as exc:
        assert exc.to_error_detail()["feature"] == "analytics"


# --- AI: POST /assistant/chat -------------------------------------------


def test_assistant_chat_is_blocked_for_a_plan_without_ai(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="chat-blocked@example.com")

    response = client.post(
        f"/organizations/{owner.organization.id}/assistant/chat",
        json={"message": "hello"},
        headers=owner.auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "feature_not_available"
    assert response.json()["detail"]["feature"] == "ai"


def test_assistant_chat_succeeds_for_a_plan_with_ai(client, db_session, fake_ai_provider):
    owner = make_org_with_owner_on_plan(db_session, email="chat-allowed@example.com", ai_enabled=True)
    fake_ai_provider.events = []

    response = client.post(
        f"/organizations/{owner.organization.id}/assistant/chat",
        json={"message": "hello"},
        headers=owner.auth_headers,
    )

    assert response.status_code == 200


# --- Analytics/Forecasting: GET /analytics/kpis and /analytics/trends -------


def test_kpis_endpoint_is_blocked_for_a_plan_without_analytics(client, db_session):
    owner = make_org_with_owner(db_session, email="kpis-blocked@example.com")

    response = client.get(
        f"/organizations/{owner.organization.id}/analytics/kpis", headers=owner.auth_headers
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "feature_not_available"
    assert response.json()["detail"]["feature"] == "analytics"


def test_trends_endpoint_is_blocked_for_a_plan_without_analytics(client, db_session):
    owner = make_org_with_owner(db_session, email="trends-blocked@example.com")

    response = client.get(
        f"/organizations/{owner.organization.id}/analytics/trends", headers=owner.auth_headers
    )

    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "analytics"


def test_trends_endpoint_reports_plan_restricted_forecasts_without_forecasting(client, db_session):
    """Starter's own capability matrix: analytics_enabled=True,
    forecasting_enabled=False -- must still get trend/comparison data,
    just with every forecast field reporting available=False,
    plan_restricted=True (never a whole-endpoint 403)."""
    owner = make_org_with_owner_on_plan(
        db_session, email="trends-no-forecast@example.com", analytics_enabled=True, forecasting_enabled=False
    )

    response = client.get(
        f"/organizations/{owner.organization.id}/analytics/trends", headers=owner.auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["invoice_count_forecast"]["available"] is False
    assert body["invoice_count_forecast"]["plan_restricted"] is True
    assert body["invoice_count_forecast"]["forecast_value"] is None
    # Trend/comparison data itself must still be present -- analytics is enabled.
    assert "invoice_count_trend" in body
    assert "revenue_series" in body


def test_trends_endpoint_forecasts_are_not_plan_restricted_with_forecasting(client, db_session):
    owner = make_org_with_owner_on_plan(
        db_session, email="trends-with-forecast@example.com", analytics_enabled=True, forecasting_enabled=True
    )

    response = client.get(
        f"/organizations/{owner.organization.id}/analytics/trends", headers=owner.auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["invoice_count_forecast"]["plan_restricted"] is False


# --- API keys / webhooks: quota enforcement via check_limit -----------------


def test_api_key_creation_is_blocked_once_the_plan_quota_is_reached(client, db_session):
    owner = make_org_with_owner_on_plan(db_session, email="apikey-quota@example.com", max_api_keys=1)

    first = client.post(
        f"/organizations/{owner.organization.id}/api-keys",
        json={"name": "Key 1", "description": "", "permissions": ["customers.read"]},
        headers=owner.auth_headers,
    )
    assert first.status_code == 201

    second = client.post(
        f"/organizations/{owner.organization.id}/api-keys",
        json={"name": "Key 2", "description": "", "permissions": ["customers.read"]},
        headers=owner.auth_headers,
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "plan_limit_reached"
    assert second.json()["detail"]["resource"] == "api_keys"


def test_webhook_creation_is_blocked_when_the_plan_allows_zero(client, db_session):
    owner = make_org_with_owner_on_plan(db_session, email="webhook-quota@example.com", max_webhooks=0)

    response = client.post(
        f"/organizations/{owner.organization.id}/webhooks",
        json={"url": "https://example.com/hook", "description": "", "subscribed_events": ["*"]},
        headers=owner.auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_limit_reached"
    assert response.json()["detail"]["resource"] == "webhooks"


def test_free_tier_defaults_block_a_second_api_key_and_any_webhook(client, db_session):
    """Regression pin for the actual seeded Free-tier values (Phase 17A's
    own backfill: max_api_keys=1, max_webhooks=0) -- this is what every
    brand-new signup is actually bound by, not just a synthetic test
    plan."""
    owner = make_org_with_owner(db_session, email="free-defaults@example.com")

    first_key = client.post(
        f"/organizations/{owner.organization.id}/api-keys",
        json={"name": "Key 1", "description": "", "permissions": ["customers.read"]},
        headers=owner.auth_headers,
    )
    assert first_key.status_code == 201

    second_key = client.post(
        f"/organizations/{owner.organization.id}/api-keys",
        json={"name": "Key 2", "description": "", "permissions": ["customers.read"]},
        headers=owner.auth_headers,
    )
    assert second_key.status_code == 409

    webhook = client.post(
        f"/organizations/{owner.organization.id}/webhooks",
        json={"url": "https://example.com/hook", "description": "", "subscribed_events": ["*"]},
        headers=owner.auth_headers,
    )
    assert webhook.status_code == 409


# --- Background jobs: silent gate on webhook delivery -----------------------


def test_no_deliveries_are_enqueued_when_background_jobs_are_disabled(db_session):
    """The event itself is still recorded (immutable history) even though
    the org's plan doesn't include background job processing -- only
    the WebhookDelivery rows (and their underlying BackgroundJob rows)
    are skipped."""
    owner = make_org_with_owner_on_plan(
        db_session,
        email="bg-jobs-disabled@example.com",
        max_webhooks=None,
        background_jobs_enabled=False,
    )
    create_endpoint(
        db_session,
        owner.organization.id,
        owner.user,
        url="https://example.com/hook",
        description="",
        subscribed_events=frozenset({WebhookEventType.customer_created}),
    )

    event, deliveries = record_webhook_event(
        db_session,
        organization_id=owner.organization.id,
        event_type=WebhookEventType.customer_created,
        object_type="customer",
        object_id="does-not-need-to-exist-for-this-test",
        payload={"id": "x"},
    )
    db_session.commit()

    assert deliveries == []
    recorded_events = db_session.query(WebhookEvent).filter_by(organization_id=owner.organization.id).all()
    assert len(recorded_events) == 1
    assert (
        db_session.query(WebhookDelivery).filter_by(organization_id=owner.organization.id).count() == 0
    )


def test_deliveries_are_enqueued_normally_when_background_jobs_are_enabled(db_session):
    owner = make_org_with_owner_on_plan(
        db_session,
        email="bg-jobs-enabled@example.com",
        max_webhooks=None,
        background_jobs_enabled=True,
    )
    create_endpoint(
        db_session,
        owner.organization.id,
        owner.user,
        url="https://example.com/hook",
        description="",
        subscribed_events=frozenset({WebhookEventType.customer_created}),
    )

    _event, deliveries = record_webhook_event(
        db_session,
        organization_id=owner.organization.id,
        event_type=WebhookEventType.customer_created,
        object_type="customer",
        object_id="does-not-need-to-exist-for-this-test",
        payload={"id": "x"},
    )
    db_session.commit()

    assert len(deliveries) == 1


# --- plan_limits.py Phase 17B refactor: still raises the same contract -----


def test_check_limit_still_raises_the_same_shape_after_the_capabilities_refactor(db_session):
    owner = make_org_with_owner_on_plan(db_session, email="check-limit-shape@example.com", max_webhooks=1)
    create_endpoint(
        db_session,
        owner.organization.id,
        owner.user,
        url="https://example.com/hook",
        description="",
        subscribed_events=frozenset({WebhookEventType.customer_created}),
    )

    try:
        check_limit(db_session, owner.organization.id, LimitedResource.webhooks)
        assert False, "expected PlanLimitExceededError"
    except PlanLimitExceededError as exc:
        detail = exc.to_error_detail()
        assert detail["code"] == "plan_limit_reached"
        assert detail["resource"] == "webhooks"
        assert detail["used"] == 1
        assert detail["limit"] == 1
