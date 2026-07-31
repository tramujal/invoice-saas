"""Tests for app.billing.service.BillingService -- the centralized
subscription lifecycle rules (Phase 17A). Exercises the service layer
directly (no HTTP), matching this repo's convention for service-layer
test files (see tests/test_plan_limits.py, tests/quotes/test_quote_lifecycle.py)."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.billing.provider_base import BillingProviderError
from app.billing.service import BillingService, InvalidPlanChangeError, InvalidSubscriptionStateError
from app.billing_period import BillingPeriod
from app.models import Organization, SubscriptionEvent
from app.subscription_event_type import SubscriptionEventType
from app.subscription_status import SubscriptionStatus
from tests.billing.fakes import FakeBillingProvider
from tests.factories import make_organization, make_plan, make_subscription, make_user


def _bare_organization(db, *, name: str) -> Organization:
    """Unlike make_organization(), this does NOT auto-create a
    Subscription -- for tests exercising BillingService.create_subscription
    itself, which would otherwise collide with the unique constraint on
    Subscription.organization_id."""
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


def test_create_subscription_without_trial_is_active_immediately(db_session):
    organization = _bare_organization(db_session, name="Billing Create Co")
    plan = make_plan(db_session, code="billing-create-plan", sort_order=5)
    actor = make_user(db_session, email="create-actor@example.com")

    subscription = BillingService(db_session).create_subscription(
        organization.id, plan.id, billing_period=BillingPeriod.monthly, actor=actor
    )

    assert subscription.status == SubscriptionStatus.active.value
    assert subscription.trial_start is None
    assert subscription.trial_end is None
    assert subscription.current_period_end > subscription.current_period_start

    events = _events(db_session, subscription)
    assert [e.event_type for e in events] == [SubscriptionEventType.subscription_created.value]
    assert events[0].actor_user_id == actor.id
    assert json.loads(events[0].new_values) == {
        "plan_id": plan.id,
        "status": "active",
        "billing_period": "monthly",
    }


def test_create_subscription_with_trial_days_starts_trialing(db_session):
    organization = _bare_organization(db_session, name="Billing Trial Co")
    plan = make_plan(db_session, code="billing-trial-plan", sort_order=5)

    subscription = BillingService(db_session).create_subscription(
        organization.id, plan.id, billing_period=BillingPeriod.yearly, trial_days=14
    )

    assert subscription.status == SubscriptionStatus.trialing.value
    assert subscription.trial_start is not None
    assert subscription.trial_end is not None
    assert (subscription.trial_end - subscription.trial_start).days == 14

    events = _events(db_session, subscription)
    assert [e.event_type for e in events] == [
        SubscriptionEventType.subscription_created.value,
        SubscriptionEventType.trial_started.value,
    ]
    # A system-triggered creation (no actor passed) leaves actor_user_id null.
    assert events[0].actor_user_id is None


def test_start_trial_on_existing_subscription(db_session):
    organization = make_organization(db_session, name="Restart Trial Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    updated = BillingService(db_session).start_trial(subscription, trial_days=7)

    assert updated.status == SubscriptionStatus.trialing.value
    assert updated.trial_start is not None
    assert (updated.trial_end - updated.trial_start).days == 7


def test_start_trial_rejects_non_positive_days(db_session):
    organization = make_organization(db_session, name="Bad Trial Co")
    subscription = make_subscription(db_session, organization)

    with pytest.raises(InvalidSubscriptionStateError):
        BillingService(db_session).start_trial(subscription, trial_days=0)


def test_expire_trial_moves_trialing_to_expired(db_session):
    organization = make_organization(db_session, name="Expire Trial Co")
    subscription = make_subscription(
        db_session,
        organization,
        status=SubscriptionStatus.trialing,
        trial_start=datetime.now(timezone.utc) - timedelta(days=15),
        trial_end=datetime.now(timezone.utc) - timedelta(days=1),
    )

    updated = BillingService(db_session).expire_trial(subscription)

    assert updated.status == SubscriptionStatus.expired.value
    assert updated.ended_at is not None
    assert _events(db_session, updated)[-1].event_type == SubscriptionEventType.trial_expired.value


def test_expire_trial_rejects_non_trialing_subscription(db_session):
    organization = make_organization(db_session, name="Not Trialing Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    with pytest.raises(InvalidSubscriptionStateError):
        BillingService(db_session).expire_trial(subscription)


def test_activate_subscription_from_trialing(db_session):
    organization = make_organization(db_session, name="Activate Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.trialing)

    updated = BillingService(db_session).activate_subscription(subscription)

    assert updated.status == SubscriptionStatus.active.value
    assert _events(db_session, updated)[-1].event_type == SubscriptionEventType.subscription_activated.value


def test_activate_subscription_is_a_noop_when_already_active(db_session):
    organization = make_organization(db_session, name="Already Active Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    BillingService(db_session).activate_subscription(subscription)

    # No event should be written for a no-op.
    assert _events(db_session, subscription) == []


def test_upgrade_plan_requires_strictly_higher_sort_order(db_session):
    organization = make_organization(db_session, name="Upgrade Co")
    low_plan = make_plan(db_session, code="upgrade-low", sort_order=1)
    high_plan = make_plan(db_session, code="upgrade-high", sort_order=2)
    subscription = make_subscription(db_session, organization, plan=low_plan)

    updated = BillingService(db_session).upgrade_plan(subscription, high_plan)

    assert updated.plan_id == high_plan.id
    event = _events(db_session, updated)[-1]
    assert event.event_type == SubscriptionEventType.plan_upgraded.value
    assert json.loads(event.previous_values) == {"plan_id": low_plan.id, "plan_code": low_plan.code}
    assert json.loads(event.new_values) == {"plan_id": high_plan.id, "plan_code": high_plan.code}


def test_upgrade_plan_rejects_a_lower_or_equal_plan(db_session):
    organization = make_organization(db_session, name="Bad Upgrade Co")
    plan_a = make_plan(db_session, code="bad-upgrade-a", sort_order=5)
    plan_b = make_plan(db_session, code="bad-upgrade-b", sort_order=5)
    subscription = make_subscription(db_session, organization, plan=plan_a)

    with pytest.raises(InvalidPlanChangeError):
        BillingService(db_session).upgrade_plan(subscription, plan_b)


def test_downgrade_plan_requires_strictly_lower_sort_order(db_session):
    organization = make_organization(db_session, name="Downgrade Co")
    high_plan = make_plan(db_session, code="downgrade-high", sort_order=9)
    low_plan = make_plan(db_session, code="downgrade-low", sort_order=1)
    subscription = make_subscription(db_session, organization, plan=high_plan)

    updated = BillingService(db_session).downgrade_plan(subscription, low_plan)

    assert updated.plan_id == low_plan.id
    assert _events(db_session, updated)[-1].event_type == SubscriptionEventType.plan_downgraded.value


def test_downgrade_plan_rejects_a_higher_or_equal_plan(db_session):
    organization = make_organization(db_session, name="Bad Downgrade Co")
    plan_a = make_plan(db_session, code="bad-downgrade-a", sort_order=5)
    plan_b = make_plan(db_session, code="bad-downgrade-b", sort_order=10)
    subscription = make_subscription(db_session, organization, plan=plan_a)

    with pytest.raises(InvalidPlanChangeError):
        BillingService(db_session).downgrade_plan(subscription, plan_b)


def test_change_plan_accepts_any_direction_including_lateral(db_session):
    """change_plan is the admin "assign this plan" action -- unlike
    upgrade_plan/downgrade_plan it never rejects based on sort_order
    direction, and a lateral move (equal sort_order) is recorded as
    manual_adjustment rather than raising."""
    organization = make_organization(db_session, name="Lateral Co")
    plan_a = make_plan(db_session, code="lateral-a", sort_order=5)
    plan_b = make_plan(db_session, code="lateral-b", sort_order=5)
    subscription = make_subscription(db_session, organization, plan=plan_a)

    updated = BillingService(db_session).change_plan(subscription, plan_b)

    assert updated.plan_id == plan_b.id
    assert _events(db_session, updated)[-1].event_type == SubscriptionEventType.manual_adjustment.value


def test_change_plan_still_classifies_real_upgrades_and_downgrades(db_session):
    organization = make_organization(db_session, name="Classify Co")
    low_plan = make_plan(db_session, code="classify-low", sort_order=1)
    high_plan = make_plan(db_session, code="classify-high", sort_order=9)
    subscription = make_subscription(db_session, organization, plan=low_plan)

    billing = BillingService(db_session)
    up = billing.change_plan(subscription, high_plan)
    assert _events(db_session, up)[-1].event_type == SubscriptionEventType.plan_upgraded.value

    down = billing.change_plan(subscription, low_plan)
    assert _events(db_session, down)[-1].event_type == SubscriptionEventType.plan_downgraded.value


def test_change_billing_period_extends_current_period_end(db_session):
    organization = make_organization(db_session, name="Period Change Co")
    subscription = make_subscription(db_session, organization, billing_period=BillingPeriod.monthly)
    previous_end = subscription.current_period_end

    updated = BillingService(db_session).change_billing_period(subscription, BillingPeriod.yearly)

    assert updated.billing_period == BillingPeriod.yearly.value
    assert updated.current_period_end > previous_end
    assert _events(db_session, updated)[-1].event_type == SubscriptionEventType.billing_period_changed.value


def test_change_billing_period_is_a_noop_when_already_on_that_period(db_session):
    organization = make_organization(db_session, name="Same Period Co")
    subscription = make_subscription(db_session, organization, billing_period=BillingPeriod.monthly)

    BillingService(db_session).change_billing_period(subscription, BillingPeriod.monthly)

    assert _events(db_session, subscription) == []


def test_renew_advances_period_from_previous_end_not_now(db_session):
    organization = make_organization(db_session, name="Renew Co")
    period_start = datetime.now(timezone.utc) - timedelta(days=40)
    period_end = period_start + timedelta(days=30)
    subscription = make_subscription(
        db_session,
        organization,
        current_period_start=period_start,
        current_period_end=period_end,
    )

    updated = BillingService(db_session).renew(subscription)

    # SQLite round-trips datetimes as naive, so compare against a
    # tzinfo-stripped expectation rather than the original aware value.
    assert updated.current_period_start == period_end.replace(tzinfo=None)
    assert updated.current_period_end == (period_end + timedelta(days=30)).replace(tzinfo=None)
    assert _events(db_session, updated)[-1].event_type == SubscriptionEventType.subscription_renewed.value


def test_cancel_immediately_sets_canceled_status_and_ended_at(db_session):
    organization = make_organization(db_session, name="Cancel Now Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    updated = BillingService(db_session).cancel_immediately(subscription)

    assert updated.status == SubscriptionStatus.canceled.value
    assert updated.canceled_at is not None
    assert updated.ended_at is not None
    event = _events(db_session, updated)[-1]
    assert event.event_type == SubscriptionEventType.subscription_canceled.value
    assert event.metadata_json is not None


def test_cancel_at_period_end_keeps_subscription_active(db_session):
    organization = make_organization(db_session, name="Cancel Later Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    updated = BillingService(db_session).cancel_at_period_end(subscription)

    assert updated.cancel_at_period_end is True
    assert updated.status == SubscriptionStatus.active.value
    assert updated.ended_at is None
    assert updated.canceled_at is not None


def test_cancel_at_period_end_is_idempotent(db_session):
    organization = make_organization(db_session, name="Idempotent Cancel Co")
    subscription = make_subscription(db_session, organization, cancel_at_period_end=True)

    BillingService(db_session).cancel_at_period_end(subscription)

    assert _events(db_session, subscription) == []


def test_reactivate_undoes_cancel_at_period_end(db_session):
    organization = make_organization(db_session, name="Reactivate Flag Co")
    subscription = make_subscription(db_session, organization, cancel_at_period_end=True)

    updated = BillingService(db_session).reactivate(subscription)

    assert updated.cancel_at_period_end is False
    assert updated.canceled_at is None


def test_reactivate_brings_a_canceled_subscription_back_to_active(db_session):
    organization = make_organization(db_session, name="Reactivate Canceled Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.canceled)
    subscription.canceled_at = datetime.now(timezone.utc)
    subscription.ended_at = datetime.now(timezone.utc)
    db_session.commit()

    updated = BillingService(db_session).reactivate(subscription)

    assert updated.status == SubscriptionStatus.active.value
    assert updated.ended_at is None


def test_reactivate_rejects_a_subscription_that_was_never_canceled(db_session):
    organization = make_organization(db_session, name="Never Canceled Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    with pytest.raises(InvalidSubscriptionStateError):
        BillingService(db_session).reactivate(subscription)


def test_cancel_immediately_pushes_to_provider_when_attached(db_session):
    organization = make_organization(db_session, name="Provider Cancel Co")
    subscription = make_subscription(
        db_session,
        organization,
        status=SubscriptionStatus.active,
        provider_name="fake",
        provider_reference="sub_123",
    )
    provider = FakeBillingProvider()

    BillingService(db_session, provider=provider).cancel_immediately(subscription)

    assert provider.cancel_subscription_calls == [
        {"provider_reference": "sub_123", "at_period_end": False}
    ]


def test_cancel_immediately_skips_provider_when_not_attached(db_session):
    organization = make_organization(db_session, name="No Provider Cancel Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)
    provider = FakeBillingProvider()

    BillingService(db_session, provider=provider).cancel_immediately(subscription)

    assert provider.cancel_subscription_calls == []


def test_cancel_immediately_leaves_local_state_untouched_on_provider_failure(db_session):
    organization = make_organization(db_session, name="Provider Failure Co")
    subscription = make_subscription(
        db_session,
        organization,
        status=SubscriptionStatus.active,
        provider_name="fake",
        provider_reference="sub_fail",
    )

    class FailingProvider(FakeBillingProvider):
        def cancel_subscription(self, *, provider_reference: str, at_period_end: bool) -> None:
            raise BillingProviderError("stripe is down")

    with pytest.raises(BillingProviderError):
        BillingService(db_session, provider=FailingProvider()).cancel_immediately(subscription)

    db_session.refresh(subscription)
    assert subscription.status == SubscriptionStatus.active.value
    assert subscription.canceled_at is None
    assert _events(db_session, subscription) == []


def test_sync_from_webhook_event_cancellation_never_pushes_back_to_provider(db_session):
    """The subscription_canceled webhook event IS the provider telling us
    this already happened -- sync_from_webhook_event must never re-push a
    cancellation back (sync_to_provider=False internally)."""
    from app.billing.provider_base import BillingProviderEventType, ProviderWebhookEvent

    organization = make_organization(db_session, name="Webhook Cancel Co")
    subscription = make_subscription(
        db_session,
        organization,
        status=SubscriptionStatus.active,
        provider_name="fake",
        provider_reference="sub_webhook",
    )
    provider = FakeBillingProvider()
    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_1",
        event_type=BillingProviderEventType.subscription_canceled,
        provider_reference="sub_webhook",
    )

    BillingService(db_session, provider=provider).sync_from_webhook_event(event)

    assert provider.cancel_subscription_calls == []


def test_cancel_at_period_end_pushes_to_provider_when_attached(db_session):
    organization = make_organization(db_session, name="Provider Cancel Later Co")
    subscription = make_subscription(
        db_session,
        organization,
        status=SubscriptionStatus.active,
        provider_name="fake",
        provider_reference="sub_later",
    )
    provider = FakeBillingProvider()

    BillingService(db_session, provider=provider).cancel_at_period_end(subscription)

    assert provider.cancel_subscription_calls == [
        {"provider_reference": "sub_later", "at_period_end": True}
    ]


def test_cancel_at_period_end_already_flagged_skips_provider_call(db_session):
    organization = make_organization(db_session, name="Already Flagged Co")
    subscription = make_subscription(
        db_session,
        organization,
        cancel_at_period_end=True,
        provider_name="fake",
        provider_reference="sub_flagged",
    )
    provider = FakeBillingProvider()

    BillingService(db_session, provider=provider).cancel_at_period_end(subscription)

    assert provider.cancel_subscription_calls == []


def test_reactivate_pushes_to_provider_when_attached(db_session):
    organization = make_organization(db_session, name="Provider Reactivate Co")
    subscription = make_subscription(
        db_session,
        organization,
        cancel_at_period_end=True,
        provider_name="fake",
        provider_reference="sub_reactivate",
    )
    provider = FakeBillingProvider()

    BillingService(db_session, provider=provider).reactivate(subscription)

    assert provider.reactivate_subscription_calls == ["sub_reactivate"]


def test_reactivate_rejected_state_never_reaches_provider(db_session):
    organization = make_organization(db_session, name="Reactivate Rejected Co")
    subscription = make_subscription(
        db_session,
        organization,
        status=SubscriptionStatus.active,
        provider_name="fake",
        provider_reference="sub_never",
    )
    provider = FakeBillingProvider()

    with pytest.raises(InvalidSubscriptionStateError):
        BillingService(db_session, provider=provider).reactivate(subscription)

    assert provider.reactivate_subscription_calls == []


def test_change_plan_pushes_to_provider_when_attached(db_session):
    organization = make_organization(db_session, name="Provider Plan Change Co")
    plan_a = make_plan(db_session, code="provider-plan-a", sort_order=1)
    plan_b = make_plan(db_session, code="provider-plan-b", sort_order=2)
    subscription = make_subscription(
        db_session,
        organization,
        plan=plan_a,
        provider_name="fake",
        provider_reference="sub_plan_change",
    )
    provider = FakeBillingProvider()

    BillingService(db_session, provider=provider).change_plan(subscription, plan_b)

    assert provider.change_subscription_plan_calls == [
        {
            "provider_reference": "sub_plan_change",
            "plan_id": plan_b.id,
            "billing_period": subscription.billing_period,
        }
    ]


def test_sync_from_webhook_event_checkout_completed_never_pushes_plan_change_to_provider(db_session):
    """checkout_completed reflects a plan the tenant's own hosted checkout
    already set on the provider's side -- attaching + recording that
    locally must never push a redundant change_subscription_plan call."""
    from app.billing.provider_base import BillingProviderEventType, ProviderWebhookEvent

    organization = make_organization(db_session, name="Webhook Checkout Co")
    plan = make_plan(db_session, code="webhook-checkout-plan", sort_order=1)
    subscription = make_subscription(db_session, organization)
    provider = FakeBillingProvider()
    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_checkout",
        event_type=BillingProviderEventType.checkout_completed,
        provider_reference="sub_checkout",
        metadata={
            "organization_id": organization.id,
            "plan_id": plan.id,
            "billing_period": subscription.billing_period,
        },
    )

    BillingService(db_session, provider=provider).sync_from_webhook_event(event)

    assert provider.change_subscription_plan_calls == []


def test_resume_moves_paused_subscription_to_active(db_session):
    organization = make_organization(db_session, name="Resume Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.paused)

    updated = BillingService(db_session).resume(subscription)

    assert updated.status == SubscriptionStatus.active.value
    assert _events(db_session, updated)[-1].event_type == SubscriptionEventType.subscription_resumed.value


def test_resume_rejects_a_subscription_that_is_not_paused(db_session):
    organization = make_organization(db_session, name="Not Paused Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    with pytest.raises(InvalidSubscriptionStateError):
        BillingService(db_session).resume(subscription)


def test_expire_subscription_sets_expired_status_and_ended_at(db_session):
    organization = make_organization(db_session, name="Expire Sub Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    updated = BillingService(db_session).expire_subscription(subscription)

    assert updated.status == SubscriptionStatus.expired.value
    assert updated.ended_at is not None
    assert _events(db_session, updated)[-1].event_type == SubscriptionEventType.subscription_expired.value


def test_validate_subscription_flags_period_end_before_start(db_session):
    organization = make_organization(db_session, name="Invalid Period Co")
    now = datetime.now(timezone.utc)
    subscription = make_subscription(
        db_session, organization, current_period_start=now, current_period_end=now - timedelta(days=1)
    )

    errors = BillingService(db_session).validate_subscription(subscription)

    assert "current_period_end must be after current_period_start" in errors


def test_validate_subscription_flags_mismatched_trial_dates(db_session):
    organization = make_organization(db_session, name="Mismatched Trial Co")
    subscription = make_subscription(
        db_session, organization, trial_start=datetime.now(timezone.utc), trial_end=None
    )

    errors = BillingService(db_session).validate_subscription(subscription)

    assert "trial_start and trial_end must be set together" in errors


def test_validate_subscription_flags_canceled_without_canceled_at(db_session):
    organization = make_organization(db_session, name="Missing Canceled At Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.canceled)

    errors = BillingService(db_session).validate_subscription(subscription)

    assert "a canceled subscription must have canceled_at set" in errors


def test_validate_subscription_returns_empty_for_a_healthy_subscription(db_session):
    organization = make_organization(db_session, name="Healthy Sub Co")
    subscription = make_subscription(db_session, organization)

    assert BillingService(db_session).validate_subscription(subscription) == []
