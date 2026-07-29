"""Fake BillingProvider -- mirrors tests/fakes.py's FakeAIProvider/
FakeEmailSender exactly. Deterministic, in-memory, no network call of any
kind; tests configure `events_to_return`/`state_to_return` directly
before the code under test runs, and assert against `.calls` afterward.

This is what proves app.billing.service.BillingService depends only on
the BillingProvider abstraction (app.billing.provider_base) and never on
a concrete provider's own wire format: every BillingService method that
touches `self.provider` (start_checkout, sync_from_webhook_event) is
tested here purely against this fake, with zero Stripe-specific
knowledge anywhere in this file.
"""

from app.billing.provider_base import (
    BillingProvider,
    CheckoutSessionRequest,
    InvalidWebhookSignatureError,
    ProviderCheckoutSession,
    ProviderCustomer,
    ProviderPortalSession,
    ProviderSubscriptionState,
    ProviderWebhookEvent,
)
from app.billing_period import BillingPeriod
from app.models import Plan

VALID_SIGNATURE = "valid-signature"


class FakeBillingProvider(BillingProvider):
    name = "fake"

    def __init__(self) -> None:
        self._customer_counter = 0
        self._checkout_counter = 0
        self._portal_counter = 0
        self.create_customer_calls: list[dict] = []
        self.create_checkout_session_calls: list[CheckoutSessionRequest] = []
        self.create_portal_session_calls: list[dict] = []
        self.cancel_subscription_calls: list[dict] = []
        self.reactivate_subscription_calls: list[str] = []
        self.change_subscription_plan_calls: list[dict] = []
        self.retrieve_subscription_calls: list[str] = []
        # Tests populate these directly before exercising the code under test.
        self.state_to_return: ProviderSubscriptionState | None = None
        self.events_to_return: list[ProviderWebhookEvent] = []
        # Lets a test simulate parse_webhook_event raising something other
        # than InvalidWebhookSignatureError (e.g.
        # UnsupportedWebhookEventError) on a validly-signed payload,
        # without needing a second signature-verification code path.
        self.error_to_raise_on_valid_signature: Exception | None = None

    def create_customer(self, *, organization_id: str, email: str, name: str) -> ProviderCustomer:
        self._customer_counter += 1
        self.create_customer_calls.append(
            {"organization_id": organization_id, "email": email, "name": name}
        )
        return ProviderCustomer(id=f"cus_fake_{self._customer_counter}", email=email)

    def create_checkout_session(self, request: CheckoutSessionRequest) -> ProviderCheckoutSession:
        self._checkout_counter += 1
        self.create_checkout_session_calls.append(request)
        return ProviderCheckoutSession(
            id=f"cs_fake_{self._checkout_counter}",
            url=f"https://fake-provider.test/checkout/{self._checkout_counter}",
        )

    def create_portal_session(self, *, customer_reference: str, return_url: str) -> ProviderPortalSession:
        self._portal_counter += 1
        self.create_portal_session_calls.append(
            {"customer_reference": customer_reference, "return_url": return_url}
        )
        return ProviderPortalSession(url=f"https://fake-provider.test/portal/{self._portal_counter}")

    def cancel_subscription(self, *, provider_reference: str, at_period_end: bool) -> None:
        self.cancel_subscription_calls.append(
            {"provider_reference": provider_reference, "at_period_end": at_period_end}
        )

    def reactivate_subscription(self, *, provider_reference: str) -> None:
        self.reactivate_subscription_calls.append(provider_reference)

    def change_subscription_plan(
        self, *, provider_reference: str, plan: Plan, billing_period: BillingPeriod
    ) -> None:
        self.change_subscription_plan_calls.append(
            {
                "provider_reference": provider_reference,
                "plan_id": plan.id,
                "billing_period": billing_period.value,
            }
        )

    def retrieve_subscription(self, *, provider_reference: str) -> ProviderSubscriptionState:
        self.retrieve_subscription_calls.append(provider_reference)
        if self.state_to_return is None:
            raise LookupError(f"FakeBillingProvider has no state configured for {provider_reference!r}")
        return self.state_to_return

    def parse_webhook_event(self, *, payload: bytes, signature_header: str) -> ProviderWebhookEvent:
        if signature_header != VALID_SIGNATURE:
            raise InvalidWebhookSignatureError("fake provider: invalid signature")
        if self.error_to_raise_on_valid_signature is not None:
            raise self.error_to_raise_on_valid_signature
        if not self.events_to_return:
            raise LookupError("FakeBillingProvider has no queued events_to_return")
        return self.events_to_return.pop(0)
