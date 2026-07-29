"""Tests for Phase 18's provider-integration additions to
app.billing.service.BillingService -- attach_provider_subscription,
mark_past_due, sync_period_from_provider, start_checkout,
sync_from_webhook_event, get_subscription_by_provider_reference. Every
test here exercises BillingService against FakeBillingProvider
(tests/billing/fakes.py) only -- proving the service depends on nothing
Stripe-specific.

Also re-confirms (test_create_subscription_with_no_provider_args_is_unchanged)
that BillingService(db) with no `provider` argument, and
create_subscription with no provider_name/provider_reference, produce
byte-for-byte the same row/event shape Phase 17A's own tests already
assert on -- the backward-compatibility guarantee this phase's user
request explicitly required.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.billing.provider_base import (
    BillingProviderEventType,
    ProviderSubscriptionState,
    ProviderWebhookEvent,
)
from app.billing.service import BillingService
from app.billing_period import BillingPeriod
from app.models import Organization, SubscriptionEvent
from app.subscription_event_type import SubscriptionEventType
from app.subscription_status import SubscriptionStatus
from tests.billing.fakes import FakeBillingProvider
from tests.factories import make_organization, make_plan, make_subscription, make_user


def _bare_organization(db, *, name: str) -> Organization:
    organization = Organization(name=name)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


def _events(db_session, subscription) -> list[SubscriptionEvent]:
    return list(
        db_session.scalars(
            select(SubscriptionEvent)
            .where(SubscriptionEvent.subscription_id == subscription.id)
            .order_by(SubscriptionEvent.created_at.asc())
        )
    )


def test_create_subscription_with_no_provider_args_is_unchanged(db_session):
    """Byte-for-byte the same as the Phase 17A behavior -- provider_name/
    provider_reference are None on the row and absent from new_values."""
    organization = _bare_organization(db_session, name="No Provider Co")
    plan = make_plan(db_session, code="no-provider-plan", sort_order=1)

    subscription = BillingService(db_session).create_subscription(organization.id, plan.id)

    assert subscription.provider_name is None
    assert subscription.provider_reference is None
    events = _events(db_session, subscription)
    assert json.loads(events[0].new_values) == {
        "plan_id": plan.id,
        "status": SubscriptionStatus.active.value,
        "billing_period": BillingPeriod.monthly.value,
    }


def test_create_subscription_with_provider_args_populates_the_row(db_session):
    organization = _bare_organization(db_session, name="Provider At Creation Co")
    plan = make_plan(db_session, code="provider-creation-plan", sort_order=1)

    subscription = BillingService(db_session).create_subscription(
        organization.id, plan.id, provider_name="stripe", provider_reference="sub_abc123"
    )

    assert subscription.provider_name == "stripe"
    assert subscription.provider_reference == "sub_abc123"
    events = _events(db_session, subscription)
    assert json.loads(events[0].new_values)["provider_name"] == "stripe"
    assert json.loads(events[0].new_values)["provider_reference"] == "sub_abc123"


def test_get_subscription_by_provider_reference_finds_the_right_row(db_session):
    organization = make_organization(db_session, name="Lookup Co")
    subscription = make_subscription(db_session, organization)
    subscription.provider_name = "stripe"
    subscription.provider_reference = "sub_lookup_1"
    db_session.commit()

    found = BillingService(db_session).get_subscription_by_provider_reference(
        provider_name="stripe", provider_reference="sub_lookup_1"
    )
    assert found is not None
    assert found.id == subscription.id


def test_get_subscription_by_provider_reference_returns_none_when_unattached(db_session):
    organization = make_organization(db_session, name="Unattached Co")
    make_subscription(db_session, organization)

    found = BillingService(db_session).get_subscription_by_provider_reference(
        provider_name="stripe", provider_reference="sub_does_not_exist"
    )
    assert found is None


def test_attach_provider_subscription_links_and_records_event(db_session):
    organization = make_organization(db_session, name="Attach Co")
    subscription = make_subscription(db_session, organization)
    actor = make_user(db_session, email="attach-actor@example.com")

    updated = BillingService(db_session).attach_provider_subscription(
        subscription, provider_name="stripe", provider_reference="sub_new_1", actor=actor
    )

    assert updated.provider_name == "stripe"
    assert updated.provider_reference == "sub_new_1"
    events = _events(db_session, subscription)
    assert events[-1].event_type == SubscriptionEventType.provider_linked.value
    assert events[-1].actor_user_id == actor.id
    assert json.loads(events[-1].previous_values) == {
        "provider_name": None,
        "provider_reference": None,
    }


def test_sync_period_from_provider_overwrites_dates_and_cancel_flag(db_session):
    organization = make_organization(db_session, name="Sync Period Co")
    now = datetime.now(timezone.utc)
    subscription = make_subscription(
        db_session, organization, current_period_start=now, current_period_end=now + timedelta(days=30)
    )
    new_start = now + timedelta(days=30)
    new_end = now + timedelta(days=60)

    updated = BillingService(db_session).sync_period_from_provider(
        subscription,
        current_period_start=new_start,
        current_period_end=new_end,
        cancel_at_period_end=True,
    )

    assert updated.current_period_start == new_start.replace(tzinfo=None)
    assert updated.current_period_end == new_end.replace(tzinfo=None)
    assert updated.cancel_at_period_end is True
    events = _events(db_session, subscription)
    assert events[-1].event_type == SubscriptionEventType.provider_subscription_updated.value


def test_mark_past_due_transitions_status_and_is_idempotent(db_session):
    organization = make_organization(db_session, name="Past Due Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    updated = BillingService(db_session).mark_past_due(subscription)
    assert updated.status == SubscriptionStatus.past_due.value
    events_after_first = _events(db_session, subscription)
    assert events_after_first[-1].event_type == SubscriptionEventType.payment_failed.value

    # Calling again on an already-past_due subscription is a no-op --
    # same "callers never have to check status first" convention as
    # activate_subscription -- so no second event is written.
    BillingService(db_session).mark_past_due(subscription)
    events_after_second = _events(db_session, subscription)
    assert len(events_after_second) == len(events_after_first)


def test_start_checkout_creates_customer_and_session_without_mutating_subscription(db_session):
    organization = make_organization(db_session, name="Checkout Co")
    subscription = make_subscription(db_session, organization)
    plan = make_plan(db_session, code="checkout-target-plan", sort_order=5)
    actor = make_user(db_session, email="checkout-actor@example.com")
    provider = FakeBillingProvider()

    session = BillingService(db_session, provider=provider).start_checkout(
        subscription,
        plan,
        BillingPeriod.yearly,
        actor=actor,
        success_url="https://app.test/success",
        cancel_url="https://app.test/cancel",
    )

    assert session.url.startswith("https://fake-provider.test/checkout/")
    assert provider.create_customer_calls == [
        {"organization_id": subscription.organization_id, "email": actor.email, "name": actor.email}
    ]
    request = provider.create_checkout_session_calls[0]
    assert request.metadata == {
        "organization_id": subscription.organization_id,
        "plan_id": plan.id,
        "billing_period": "yearly",
    }
    # No mutation of any kind until a checkout_completed webhook event
    # arrives (see BillingProvider.create_checkout_session's own docstring).
    db_session.refresh(subscription)
    assert subscription.provider_name is None
    assert subscription.plan_id != plan.id


def test_sync_from_webhook_event_checkout_completed_attaches_and_changes_plan(db_session):
    organization = make_organization(db_session, name="Webhook Checkout Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.trialing)
    plan = make_plan(db_session, code="webhook-checkout-plan", sort_order=9)
    provider = FakeBillingProvider()

    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_checkout_1",
        event_type=BillingProviderEventType.checkout_completed,
        provider_reference="sub_from_checkout",
        metadata={
            "organization_id": organization.id,
            "plan_id": plan.id,
            "billing_period": "yearly",
        },
    )

    updated = BillingService(db_session, provider=provider).sync_from_webhook_event(event)

    assert updated.provider_name == "fake"
    assert updated.provider_reference == "sub_from_checkout"
    assert updated.plan_id == plan.id
    assert updated.billing_period == "yearly"
    assert updated.status == SubscriptionStatus.active.value


def test_sync_from_webhook_event_checkout_completed_raises_for_unknown_organization(db_session):
    provider = FakeBillingProvider()
    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_checkout_missing",
        event_type=BillingProviderEventType.checkout_completed,
        provider_reference="sub_x",
        metadata={"organization_id": "org-does-not-exist", "plan_id": "plan-x", "billing_period": "monthly"},
    )
    with pytest.raises(LookupError):
        BillingService(db_session, provider=provider).sync_from_webhook_event(event)


def test_sync_from_webhook_event_subscription_updated_syncs_period(db_session):
    organization = make_organization(db_session, name="Webhook Update Co")
    subscription = make_subscription(db_session, organization)
    subscription.provider_name = "fake"
    subscription.provider_reference = "sub_update_1"
    db_session.commit()
    provider = FakeBillingProvider()

    new_start = datetime.now(timezone.utc)
    new_end = new_start + timedelta(days=30)
    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_update_1",
        event_type=BillingProviderEventType.subscription_updated,
        provider_reference="sub_update_1",
        subscription_state=ProviderSubscriptionState(
            provider_reference="sub_update_1",
            status="active",
            current_period_start=new_start,
            current_period_end=new_end,
            cancel_at_period_end=False,
        ),
    )

    updated = BillingService(db_session, provider=provider).sync_from_webhook_event(event)
    assert updated.current_period_start == new_start.replace(tzinfo=None)
    assert updated.current_period_end == new_end.replace(tzinfo=None)


def test_sync_from_webhook_event_subscription_canceled_cancels_immediately(db_session):
    organization = make_organization(db_session, name="Webhook Cancel Co")
    subscription = make_subscription(db_session, organization)
    subscription.provider_name = "fake"
    subscription.provider_reference = "sub_cancel_1"
    db_session.commit()
    provider = FakeBillingProvider()

    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_cancel_1",
        event_type=BillingProviderEventType.subscription_canceled,
        provider_reference="sub_cancel_1",
    )

    updated = BillingService(db_session, provider=provider).sync_from_webhook_event(event)
    assert updated.status == SubscriptionStatus.canceled.value
    assert updated.ended_at is not None


def test_sync_from_webhook_event_payment_failed_marks_past_due(db_session):
    organization = make_organization(db_session, name="Webhook Payment Failed Co")
    subscription = make_subscription(db_session, organization)
    subscription.provider_name = "fake"
    subscription.provider_reference = "sub_pf_1"
    db_session.commit()
    provider = FakeBillingProvider()

    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_pf_1",
        event_type=BillingProviderEventType.payment_failed,
        provider_reference="sub_pf_1",
    )

    updated = BillingService(db_session, provider=provider).sync_from_webhook_event(event)
    assert updated.status == SubscriptionStatus.past_due.value


def test_sync_from_webhook_event_raises_for_unattached_provider_reference(db_session):
    provider = FakeBillingProvider()
    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_unknown_1",
        event_type=BillingProviderEventType.payment_failed,
        provider_reference="sub_never_attached",
    )
    with pytest.raises(LookupError):
        BillingService(db_session, provider=provider).sync_from_webhook_event(event)


def test_start_portal_session_raises_when_no_provider_customer_exists(db_session):
    organization = make_organization(db_session, name="Portal No Customer Co")
    subscription = make_subscription(db_session, organization)
    provider = FakeBillingProvider()

    with pytest.raises(LookupError):
        BillingService(db_session, provider=provider).start_portal_session(
            subscription, return_url="https://app.test/settings/plan"
        )


def test_start_portal_session_uses_the_cached_customer(db_session):
    organization = make_organization(db_session, name="Portal With Customer Co")
    subscription = make_subscription(db_session, organization)
    plan = make_plan(db_session, code="portal-plan", sort_order=1)
    actor = make_user(db_session, email="portal-actor@example.com")
    provider = FakeBillingProvider()
    service = BillingService(db_session, provider=provider)

    # Establishes a cached ProviderCustomer the same way a real checkout would.
    service.start_checkout(
        subscription, plan, BillingPeriod.monthly, actor=actor,
        success_url="https://app.test/success", cancel_url="https://app.test/cancel",
    )

    session = service.start_portal_session(subscription, return_url="https://app.test/settings/plan")

    assert session.url.startswith("https://fake-provider.test/portal/")
    assert provider.create_portal_session_calls == [
        {"customer_reference": "cus_fake_1", "return_url": "https://app.test/settings/plan"}
    ]
