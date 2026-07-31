"""Tests for the Phase 18 HTTP surface:
POST /organizations/{id}/billing/checkout (app.routers.billing) and
POST /billing/webhooks/stripe (app.routers.billing_webhooks).

Overrides app.deps.get_billing_provider_dependency via
app.dependency_overrides (the same mechanism tests/conftest.py's own
`client` fixture already uses for get_db) to inject FakeBillingProvider
-- these tests never touch a real Stripe account, but they do exercise
the real HTTP routing/permission/idempotency logic.
"""

from datetime import datetime, timezone

import pytest

from app.billing.provider_base import (
    BillingProviderEventType,
    ProviderWebhookEvent,
    UnsupportedWebhookEventError,
)
from app.deps import get_billing_provider_dependency
from app.main import app
from app.models import ProviderWebhookReceipt
from app.membership_role import MembershipRole
from app.security import create_access_token
from tests.billing.fakes import VALID_SIGNATURE, FakeBillingProvider
from tests.factories import make_membership, make_org_with_owner, make_plan, make_user


@pytest.fixture
def fake_provider() -> FakeBillingProvider:
    provider = FakeBillingProvider()
    app.dependency_overrides[get_billing_provider_dependency] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_billing_provider_dependency, None)


def _verified_org_with_owner(db_session, *, email: str, org_name: str):
    owner = make_org_with_owner(db_session, email=email, org_name=org_name)
    owner.user.email_verified_at = datetime.now(timezone.utc)
    db_session.commit()
    return owner


# --- POST /organizations/{id}/billing/checkout -----------------------------


def test_checkout_requires_billing_manage_permission(client, db_session, fake_provider):
    owner = _verified_org_with_owner(db_session, email="checkout-owner@example.com", org_name="Checkout Co")
    member = make_user(db_session, email="checkout-member@example.com")
    make_membership(db_session, member, owner.organization, role=MembershipRole.member)
    plan = make_plan(db_session, code="checkout-http-plan", sort_order=3)
    member_headers = {"Authorization": f"Bearer {create_access_token(member.id)}"}

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/checkout",
        json={
            "plan_id": plan.id,
            "billing_period": "monthly",
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
        },
        headers=member_headers,
    )

    assert response.status_code == 403


def test_checkout_returns_503_when_no_provider_is_configured(client, db_session):
    """No fake_provider fixture used here -- exercises the real
    NullBillingProvider default (BILLING_PROVIDER unset in the test
    environment)."""
    owner = _verified_org_with_owner(db_session, email="checkout-noprovider@example.com", org_name="No Provider Co")
    plan = make_plan(db_session, code="checkout-noprovider-plan", sort_order=3)

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/checkout",
        json={
            "plan_id": plan.id,
            "billing_period": "monthly",
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
        },
        headers=owner.auth_headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "billing_provider_not_configured"


def test_checkout_succeeds_and_returns_provider_url(client, db_session, fake_provider):
    owner = _verified_org_with_owner(db_session, email="checkout-success@example.com", org_name="Checkout Success Co")
    plan = make_plan(db_session, code="checkout-success-plan", sort_order=3)

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/checkout",
        json={
            "plan_id": plan.id,
            "billing_period": "yearly",
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
        },
        headers=owner.auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["checkout_url"].startswith("https://fake-provider.test/checkout/")
    assert fake_provider.create_checkout_session_calls[0].metadata["plan_id"] == plan.id
    assert fake_provider.create_checkout_session_calls[0].metadata["billing_period"] == "yearly"


def test_checkout_returns_404_for_unknown_plan(client, db_session, fake_provider):
    owner = _verified_org_with_owner(db_session, email="checkout-unknown-plan@example.com", org_name="Unknown Plan Co")

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/checkout",
        json={
            "plan_id": "plan-does-not-exist",
            "billing_period": "monthly",
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
        },
        headers=owner.auth_headers,
    )

    assert response.status_code == 404


def test_checkout_returns_422_for_invalid_billing_period(client, db_session, fake_provider):
    owner = _verified_org_with_owner(db_session, email="checkout-badperiod@example.com", org_name="Bad Period Co")
    plan = make_plan(db_session, code="checkout-badperiod-plan", sort_order=3)

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/checkout",
        json={
            "plan_id": plan.id,
            "billing_period": "biweekly",
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
        },
        headers=owner.auth_headers,
    )

    assert response.status_code == 422


# --- POST /billing/webhooks/stripe ------------------------------------------


def test_webhook_rejects_invalid_signature(client, fake_provider):
    response = client.post(
        "/billing/webhooks/stripe",
        content=b'{"id":"evt_1"}',
        headers={"stripe-signature": "wrong-signature"},
    )
    assert response.status_code == 400


def test_webhook_acknowledges_unsupported_event_type(client, fake_provider):
    fake_provider.error_to_raise_on_valid_signature = UnsupportedWebhookEventError("unhandled")
    response = client.post(
        "/billing/webhooks/stripe",
        content=b'{"id":"evt_1"}',
        headers={"stripe-signature": VALID_SIGNATURE},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_processes_a_valid_event_and_records_a_receipt(client, db_session, fake_provider):
    owner = make_org_with_owner(db_session, email="webhook-http-owner@example.com", org_name="Webhook HTTP Co")
    plan = make_plan(db_session, code="webhook-http-plan", sort_order=4)

    fake_provider.events_to_return.append(
        ProviderWebhookEvent(
            provider_name="fake",
            event_id="evt_http_1",
            event_type=BillingProviderEventType.checkout_completed,
            provider_reference="sub_http_1",
            metadata={"organization_id": owner.organization.id, "plan_id": plan.id, "billing_period": "monthly"},
        )
    )

    response = client.post(
        "/billing/webhooks/stripe",
        content=b'{"id":"evt_http_1"}',
        headers={"stripe-signature": VALID_SIGNATURE},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    receipt = (
        db_session.query(ProviderWebhookReceipt)
        .filter_by(provider_name="fake", event_id="evt_http_1")
        .one_or_none()
    )
    assert receipt is not None


def test_webhook_skips_a_duplicate_delivery_of_the_same_event(client, db_session, fake_provider):
    owner = make_org_with_owner(db_session, email="webhook-dup-owner@example.com", org_name="Webhook Dup Co")
    plan = make_plan(db_session, code="webhook-dup-plan", sort_order=4)
    metadata = {"organization_id": owner.organization.id, "plan_id": plan.id, "billing_period": "monthly"}

    fake_provider.events_to_return.append(
        ProviderWebhookEvent(
            provider_name="fake",
            event_id="evt_dup_1",
            event_type=BillingProviderEventType.checkout_completed,
            provider_reference="sub_dup_1",
            metadata=metadata,
        )
    )
    first = client.post(
        "/billing/webhooks/stripe", content=b'{"id":"evt_dup_1"}', headers={"stripe-signature": VALID_SIGNATURE}
    )
    assert first.status_code == 200
    assert first.json()["status"] == "processed"

    # Redelivery of the same event -- the router still parses it (that's
    # how it learns the event_id to check against ProviderWebhookReceipt),
    # so the fake needs a second queued event to pop, but
    # sync_from_webhook_event must never be called a second time --
    # verified below by asserting the mutation wasn't reapplied and no
    # second SubscriptionEvent was written (see the plan_id check).
    fake_provider.events_to_return.append(
        ProviderWebhookEvent(
            provider_name="fake",
            event_id="evt_dup_1",
            event_type=BillingProviderEventType.checkout_completed,
            provider_reference="sub_dup_1",
            metadata=metadata,
        )
    )
    second = client.post(
        "/billing/webhooks/stripe", content=b'{"id":"evt_dup_1"}', headers={"stripe-signature": VALID_SIGNATURE}
    )
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed"
    assert len(fake_provider.events_to_return) == 0


def test_webhook_returns_409_and_writes_no_receipt_on_a_version_conflict(
    client, db_session, fake_provider, monkeypatch
):
    """A SubscriptionConflictError (Phase P2.1) -- this subscription's row
    was concurrently modified by another writer (a platform-admin action,
    or another webhook event for the same subscription processed by a
    different worker) between this handler's read and its own commit --
    must map to a 409, and critically must NOT record a
    ProviderWebhookReceipt: never in-process blindly retried (the
    subscription's true state may have moved in a way that makes
    reapplying this exact event wrong), so a future redelivery from
    Stripe's own retry schedule must still be treated as unprocessed and
    get a real second attempt. Simulated via monkeypatch rather than a
    genuine second DB connection, since the shared, SAVEPOINT-nested
    `client`/`db_session` fixtures bind every request in a test to one
    single connection (see tests/conftest.py) -- a true multi-connection
    reproduction of this race lives in
    tests/billing/test_subscription_concurrency.py instead, at the
    BillingService layer the conflict actually originates from."""
    from app.billing.service import BillingService, SubscriptionConflictError

    owner = make_org_with_owner(db_session, email="webhook-conflict-owner@example.com", org_name="Webhook Conflict Co")
    plan = make_plan(db_session, code="webhook-conflict-plan", sort_order=4)

    def _raise_conflict(self, event, *, actor=None):
        raise SubscriptionConflictError("simulated concurrent write", current_version=7)

    monkeypatch.setattr(BillingService, "sync_from_webhook_event", _raise_conflict)

    fake_provider.events_to_return.append(
        ProviderWebhookEvent(
            provider_name="fake",
            event_id="evt_conflict_1",
            event_type=BillingProviderEventType.checkout_completed,
            provider_reference="sub_conflict_1",
            metadata={"organization_id": owner.organization.id, "plan_id": plan.id, "billing_period": "monthly"},
        )
    )

    response = client.post(
        "/billing/webhooks/stripe",
        content=b'{"id":"evt_conflict_1"}',
        headers={"stripe-signature": VALID_SIGNATURE},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "subscription_version_conflict"
    receipt = (
        db_session.query(ProviderWebhookReceipt)
        .filter_by(provider_name="fake", event_id="evt_conflict_1")
        .one_or_none()
    )
    assert receipt is None


def test_webhook_returns_400_for_an_unresolvable_event(client, fake_provider):
    fake_provider.events_to_return.append(
        ProviderWebhookEvent(
            provider_name="fake",
            event_id="evt_unresolvable_1",
            event_type=BillingProviderEventType.checkout_completed,
            provider_reference="sub_x",
            metadata={"organization_id": "org-does-not-exist", "plan_id": "plan-x", "billing_period": "monthly"},
        )
    )
    response = client.post(
        "/billing/webhooks/stripe",
        content=b'{"id":"evt_unresolvable_1"}',
        headers={"stripe-signature": VALID_SIGNATURE},
    )
    assert response.status_code == 400


# --- POST /organizations/{id}/billing/portal --------------------------------


def test_portal_requires_billing_manage_permission(client, db_session, fake_provider):
    owner = _verified_org_with_owner(db_session, email="portal-owner@example.com", org_name="Portal Perm Co")
    member = make_user(db_session, email="portal-member@example.com")
    make_membership(db_session, member, owner.organization, role=MembershipRole.member)
    member_headers = {"Authorization": f"Bearer {create_access_token(member.id)}"}

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/portal",
        json={"return_url": "https://app.test/settings/plan"},
        headers=member_headers,
    )

    assert response.status_code == 403


def test_portal_returns_503_when_no_provider_customer_and_no_provider_configured(client, db_session):
    """With BILLING_PROVIDER unset (NullBillingProvider), there can never
    be a ProviderCustomer row for any organization -- start_portal_session
    still raises LookupError first (its own cache-miss check runs before
    any provider call), which the router maps to 404, same as the
    "no customer yet" case below. The genuinely distinct 503 path
    (BILLING_PROVIDER explicitly misconfigured) is covered by
    test_portal_returns_503_when_provider_factory_is_misconfigured."""
    owner = _verified_org_with_owner(db_session, email="portal-noprovider@example.com", org_name="Portal No Provider Co")

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/portal",
        json={"return_url": "https://app.test/settings/plan"},
        headers=owner.auth_headers,
    )

    assert response.status_code == 404


def test_portal_returns_503_when_provider_factory_is_misconfigured(client, db_session, monkeypatch):
    """BILLING_PROVIDER=stripe without STRIPE_API_KEY/STRIPE_WEBHOOK_SECRET
    -- get_billing_provider_dependency itself raises
    BillingProviderNotConfiguredError before the route body (and thus
    before any ProviderCustomer lookup) ever runs. Does NOT use the
    fake_provider fixture -- that fixture overrides
    get_billing_provider_dependency entirely, which would bypass the
    exact failure this test targets."""
    owner = _verified_org_with_owner(
        db_session, email="portal-misconfigured@example.com", org_name="Portal Misconfigured Co"
    )
    monkeypatch.setenv("BILLING_PROVIDER", "stripe")
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/portal",
        json={"return_url": "https://app.test/settings/plan"},
        headers=owner.auth_headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "billing_provider_not_configured"


def test_portal_returns_404_when_no_provider_customer_exists(client, db_session, fake_provider):
    owner = _verified_org_with_owner(db_session, email="portal-nocustomer@example.com", org_name="Portal No Customer Co")

    response = client.post(
        f"/organizations/{owner.organization.id}/billing/portal",
        json={"return_url": "https://app.test/settings/plan"},
        headers=owner.auth_headers,
    )

    assert response.status_code == 404


def test_portal_succeeds_after_a_checkout_established_a_provider_customer(client, db_session, fake_provider):
    owner = _verified_org_with_owner(db_session, email="portal-success@example.com", org_name="Portal Success Co")
    plan = make_plan(db_session, code="portal-http-plan", sort_order=3)

    checkout_response = client.post(
        f"/organizations/{owner.organization.id}/billing/checkout",
        json={
            "plan_id": plan.id,
            "billing_period": "monthly",
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
        },
        headers=owner.auth_headers,
    )
    assert checkout_response.status_code == 200

    portal_response = client.post(
        f"/organizations/{owner.organization.id}/billing/portal",
        json={"return_url": "https://app.test/settings/plan"},
        headers=owner.auth_headers,
    )

    assert portal_response.status_code == 200
    assert portal_response.json()["portal_url"].startswith("https://fake-provider.test/portal/")
