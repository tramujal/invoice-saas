"""Contract tests for BillingProvider implementations -- proves
FakeBillingProvider (and, by the same shape, any future concrete
provider) actually satisfies the abstraction app.billing.service
.BillingService is written against. Deliberately provider-agnostic
assertions only (shapes, not any specific provider's wire format)."""

import pytest

from app.billing.provider_base import (
    BillingProviderEventType,
    CheckoutSessionRequest,
    InvalidWebhookSignatureError,
    ProviderCheckoutSession,
    ProviderCustomer,
    ProviderSubscriptionState,
    ProviderWebhookEvent,
)
from app.billing_period import BillingPeriod
from tests.billing.fakes import VALID_SIGNATURE, FakeBillingProvider
from tests.factories import make_plan


@pytest.fixture
def provider() -> FakeBillingProvider:
    return FakeBillingProvider()


def test_name_is_a_non_empty_string(provider: FakeBillingProvider):
    assert isinstance(provider.name, str)
    assert provider.name


def test_create_customer_returns_matching_email(provider: FakeBillingProvider):
    customer = provider.create_customer(organization_id="org-1", email="owner@example.com", name="Acme")
    assert isinstance(customer, ProviderCustomer)
    assert customer.email == "owner@example.com"
    assert customer.id


def test_create_checkout_session_returns_a_usable_url(db_session, provider: FakeBillingProvider):
    plan = make_plan(db_session, code="contract-plan", sort_order=1)
    request = CheckoutSessionRequest(
        customer_reference="cus_1",
        plan=plan,
        billing_period=BillingPeriod.monthly,
        success_url="https://app.test/success",
        cancel_url="https://app.test/cancel",
        metadata={"organization_id": "org-1", "plan_id": plan.id, "billing_period": "monthly"},
    )
    session = provider.create_checkout_session(request)
    assert isinstance(session, ProviderCheckoutSession)
    assert session.url.startswith("https://")
    assert session.id


def test_cancel_reactivate_change_plan_do_not_raise(db_session, provider: FakeBillingProvider):
    plan = make_plan(db_session, code="contract-plan-2", sort_order=2)
    provider.cancel_subscription(provider_reference="sub_1", at_period_end=True)
    provider.reactivate_subscription(provider_reference="sub_1")
    provider.change_subscription_plan(
        provider_reference="sub_1", plan=plan, billing_period=BillingPeriod.yearly
    )
    assert provider.cancel_subscription_calls == [
        {"provider_reference": "sub_1", "at_period_end": True}
    ]
    assert provider.reactivate_subscription_calls == ["sub_1"]
    assert provider.change_subscription_plan_calls == [
        {"provider_reference": "sub_1", "plan_id": plan.id, "billing_period": "yearly"}
    ]


def test_retrieve_subscription_returns_configured_state(provider: FakeBillingProvider):
    from datetime import datetime, timezone

    state = ProviderSubscriptionState(
        provider_reference="sub_1",
        status="active",
        current_period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        current_period_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        cancel_at_period_end=False,
    )
    provider.state_to_return = state
    result = provider.retrieve_subscription(provider_reference="sub_1")
    assert result == state


def test_retrieve_subscription_raises_when_not_configured(provider: FakeBillingProvider):
    with pytest.raises(LookupError):
        provider.retrieve_subscription(provider_reference="sub_unknown")


def test_parse_webhook_event_rejects_invalid_signature(provider: FakeBillingProvider):
    with pytest.raises(InvalidWebhookSignatureError):
        provider.parse_webhook_event(payload=b"{}", signature_header="not-valid")


def test_parse_webhook_event_returns_queued_event_on_valid_signature(provider: FakeBillingProvider):
    event = ProviderWebhookEvent(
        provider_name="fake",
        event_id="evt_1",
        event_type=BillingProviderEventType.subscription_canceled,
        provider_reference="sub_1",
    )
    provider.events_to_return.append(event)
    result = provider.parse_webhook_event(payload=b"{}", signature_header=VALID_SIGNATURE)
    assert result == event
