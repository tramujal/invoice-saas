"""The default BillingProvider -- selected whenever BILLING_PROVIDER is
unset (see app.billing.provider_factory.get_billing_provider). This is
what makes the whole payment-provider layer strictly additive: every
existing BillingService(db) call site (registration, platform-admin plan
changes, every test written before Phase 18) keeps constructing a
BillingService with zero config and zero behavior change, because
`provider` defaults to NullBillingProvider() rather than None -- there is
never a None-check scattered through BillingService's own methods.

Every method fails closed (raises BillingProviderNotConfiguredError)
rather than silently no-oping. A payment feature that pretends to
succeed while doing nothing is far more dangerous than one that refuses
clearly -- the same fail-closed instinct app.role_hierarchy and
app.deps.require_permission already apply to permission checks.
"""

from app.billing.provider_base import (
    BillingProvider,
    BillingProviderNotConfiguredError,
    CheckoutSessionRequest,
    ProviderCheckoutSession,
    ProviderCustomer,
    ProviderPortalSession,
    ProviderSubscriptionState,
    ProviderWebhookEvent,
)
from app.billing_period import BillingPeriod
from app.models import Plan

_NOT_CONFIGURED_MESSAGE = (
    "No payment provider is configured (BILLING_PROVIDER is unset or 'none'). "
    "Set BILLING_PROVIDER to a supported provider (e.g. 'stripe') and its "
    "required configuration to enable provider-backed billing."
)


class NullBillingProvider(BillingProvider):
    name = "none"

    def create_customer(self, *, organization_id: str, email: str, name: str) -> ProviderCustomer:
        raise BillingProviderNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

    def create_checkout_session(self, request: CheckoutSessionRequest) -> ProviderCheckoutSession:
        raise BillingProviderNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

    def create_portal_session(self, *, customer_reference: str, return_url: str) -> ProviderPortalSession:
        raise BillingProviderNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

    def cancel_subscription(self, *, provider_reference: str, at_period_end: bool) -> None:
        raise BillingProviderNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

    def reactivate_subscription(self, *, provider_reference: str) -> None:
        raise BillingProviderNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

    def change_subscription_plan(
        self, *, provider_reference: str, plan: Plan, billing_period: BillingPeriod
    ) -> None:
        raise BillingProviderNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

    def retrieve_subscription(self, *, provider_reference: str) -> ProviderSubscriptionState:
        raise BillingProviderNotConfiguredError(_NOT_CONFIGURED_MESSAGE)

    def parse_webhook_event(self, *, payload: bytes, signature_header: str) -> ProviderWebhookEvent:
        raise BillingProviderNotConfiguredError(_NOT_CONFIGURED_MESSAGE)
