"""Tests for SubscriptionEvent -- subscription HISTORY (Phase 17A),
distinct from PlatformAuditLog (see app.models.SubscriptionEvent's own
docstring). Focuses on the shape and accumulation of the event trail
itself, complementing tests/billing/test_billing_service.py's per-method
event-type assertions."""

import json

import pytest
from sqlalchemy import select

from app.billing.service import BillingService, InvalidSubscriptionStateError
from app.billing_period import BillingPeriod
from app.models import Organization, SubscriptionEvent
from app.subscription_event_type import SubscriptionEventType
from app.subscription_status import SubscriptionStatus
from tests.factories import make_organization, make_plan, make_subscription, make_user


def _bare_organization(db, *, name: str) -> Organization:
    """Unlike make_organization(), this does NOT auto-create a
    Subscription -- needed here since create_subscription() would
    otherwise collide with the unique constraint on
    Subscription.organization_id."""
    organization = Organization(name=name)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


def _events_for_subscription(db_session, subscription_id: str) -> list[SubscriptionEvent]:
    return list(
        db_session.scalars(
            select(SubscriptionEvent)
            .where(SubscriptionEvent.subscription_id == subscription_id)
            .order_by(SubscriptionEvent.created_at.asc())
        )
    )


def test_events_accumulate_in_chronological_order_across_a_lifecycle(db_session):
    organization = make_organization(db_session, name="Event History Co")
    low_plan = make_plan(db_session, code="event-history-low", sort_order=1)
    high_plan = make_plan(db_session, code="event-history-high", sort_order=9)
    subscription = make_subscription(db_session, organization, plan=low_plan)
    actor = make_user(db_session, email="event-history-actor@example.com")

    billing = BillingService(db_session)
    billing.upgrade_plan(subscription, high_plan, actor=actor)
    billing.change_billing_period(subscription, BillingPeriod.yearly, actor=actor)
    billing.cancel_at_period_end(subscription, actor=actor)
    billing.reactivate(subscription, actor=actor)

    events = _events_for_subscription(db_session, subscription.id)

    assert [e.event_type for e in events] == [
        SubscriptionEventType.plan_upgraded.value,
        SubscriptionEventType.billing_period_changed.value,
        SubscriptionEventType.subscription_canceled.value,
        SubscriptionEventType.subscription_reactivated.value,
    ]
    # created_at is monotonically non-decreasing in insertion order.
    timestamps = [e.created_at for e in events]
    assert timestamps == sorted(timestamps)


def test_every_event_row_carries_both_subscription_id_and_organization_id(db_session):
    """Both are indexed columns (see app.models.SubscriptionEvent's own
    __table_args__) so history can be queried either by a specific
    subscription or across an organization without a join."""
    organization = make_organization(db_session, name="Dual Index Co")
    subscription = make_subscription(db_session, organization)

    BillingService(db_session).cancel_immediately(subscription)

    event = _events_for_subscription(db_session, subscription.id)[0]
    assert event.organization_id == organization.id
    assert event.subscription_id == subscription.id


def test_system_triggered_event_has_no_actor(db_session):
    """create_subscription is called without an actor when there is no
    human initiating it (e.g. a future scheduled job) -- actor_user_id
    must be nullable and actually null in that case."""
    organization = _bare_organization(db_session, name="System Trigger Co")
    plan = make_plan(db_session, code="system-trigger-plan", sort_order=1)

    subscription = BillingService(db_session).create_subscription(organization.id, plan.id)

    event = _events_for_subscription(db_session, subscription.id)[0]
    assert event.actor_user_id is None


def test_human_triggered_event_records_the_actor(db_session):
    organization = make_organization(db_session, name="Human Trigger Co")
    subscription = make_subscription(db_session, organization)
    actor = make_user(db_session, email="human-trigger-actor@example.com")

    BillingService(db_session).cancel_immediately(subscription, actor=actor)

    event = _events_for_subscription(db_session, subscription.id)[-1]
    assert event.actor_user_id == actor.id


def test_previous_and_new_values_round_trip_as_json(db_session):
    organization = make_organization(db_session, name="JSON Roundtrip Co")
    low_plan = make_plan(db_session, code="json-roundtrip-low", sort_order=1)
    high_plan = make_plan(db_session, code="json-roundtrip-high", sort_order=9)
    subscription = make_subscription(db_session, organization, plan=low_plan)

    BillingService(db_session).upgrade_plan(subscription, high_plan)

    event = _events_for_subscription(db_session, subscription.id)[0]
    assert event.previous_values is not None
    assert event.new_values is not None

    previous = json.loads(event.previous_values)
    new = json.loads(event.new_values)
    assert previous == {"plan_id": low_plan.id, "plan_code": low_plan.code}
    assert new == {"plan_id": high_plan.id, "plan_code": high_plan.code}


def test_no_event_is_written_for_a_rejected_lifecycle_transition(db_session):
    """A failed InvalidSubscriptionStateError call must not leave a
    partial/misleading event row behind."""
    organization = make_organization(db_session, name="Rejected Transition Co")
    subscription = make_subscription(db_session, organization, status=SubscriptionStatus.active)

    with pytest.raises(InvalidSubscriptionStateError):
        BillingService(db_session).resume(subscription)

    assert _events_for_subscription(db_session, subscription.id) == []
