"""Provider-agnostic payment-provider interface.

Mirrors app/ai/base.py and app/email/base.py exactly: app.billing.service
.BillingService depends only on BillingProvider and the value
objects/exceptions declared here -- never on a concrete provider SDK or
its wire format. Adding a new underlying provider (Stripe today; a future
Mercado Pago/Paddle/LemonSqueezy) means writing a new class implementing
this interface and adding one branch in app.billing.provider_factory
.get_billing_provider() -- nothing in app.billing.service, any router, or
any other caller changes.

This module is intentionally free of any provider-specific vocabulary.
Concrete providers translate their own wire format (Stripe's
"checkout.session.completed", Mercado Pago's "payment.created", etc.)
into the small, normalized BillingProviderEventType vocabulary below --
that translation is the ONE place a provider's own event naming is
allowed to leak into this codebase.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.billing_period import BillingPeriod
from app.models import Plan


class BillingProviderError(Exception):
    """Base class for every error a BillingProvider implementation raises.
    Callers (BillingService, routers) catch this rather than a provider's
    own SDK/HTTP exception types, exactly like AIProviderError/
    EmailSendError -- what actually failed (auth, network, malformed
    response) is provider-specific and logged by the provider itself;
    everything above this layer only needs to know "the provider call
    failed"."""


class BillingProviderNotConfiguredError(BillingProviderError):
    """Raised when a provider-dependent operation is attempted but no
    provider (or an incomplete one) is configured -- e.g. BILLING_PROVIDER
    unset (NullBillingProvider, see app.billing.null_provider) or set to
    "stripe" without STRIPE_API_KEY. Distinct from BillingProviderRequestError:
    this is a configuration problem, never a network/API failure, so
    callers can surface a clean "not available" message without retrying."""


class BillingProviderRequestError(BillingProviderError):
    """Raised when a configured provider's API call itself fails (network
    error, non-2xx response, malformed response body)."""


class InvalidWebhookSignatureError(BillingProviderError):
    """Raised by parse_webhook_event when the signature header doesn't
    verify against the configured webhook secret, or the payload's
    timestamp is outside the provider's replay-tolerance window. Callers
    (app.routers.billing_webhooks) must map this to a 400, never process
    the payload."""


class UnsupportedWebhookEventError(BillingProviderError):
    """Raised by parse_webhook_event when the signature verifies but the
    provider's own event type has no corresponding
    BillingProviderEventType -- a real, expected occurrence (a payment
    provider fires many event types this app has no reason to react to).
    Distinct from InvalidWebhookSignatureError: app.routers.billing_webhooks
    maps this to a 200 (acknowledge, do nothing), never a 400 -- the
    provider must not keep retrying an event that will never be handled."""


class BillingProviderEventType(str, Enum):
    """The normalized vocabulary every concrete provider's
    parse_webhook_event() must translate its own event names into. This
    is the entire surface app.billing.service.BillingService
    .sync_from_webhook_event() switches on -- it never sees a provider's
    own event-type string."""

    # A checkout session (see BillingProvider.create_checkout_session) was
    # completed -- the organization should be attached to this provider
    # subscription and moved onto the plan/billing_period it checked out
    # for.
    checkout_completed = "checkout_completed"
    # The provider's own subscription record changed in a way that moves
    # our current_period_start/end (a renewal, or the provider's own
    # billing-cycle bookkeeping) -- see BillingService
    # .sync_period_from_provider, which trusts the provider's dates
    # directly rather than recomputing them locally.
    subscription_updated = "subscription_updated"
    # The provider's subscription ended (canceled on the provider's side,
    # whether immediately or at period end -- see
    # ProviderSubscriptionState.cancel_at_period_end).
    subscription_canceled = "subscription_canceled"
    # A renewal payment attempt failed -- see BillingService
    # .mark_past_due.
    payment_failed = "payment_failed"


@dataclass(frozen=True)
class ProviderCustomer:
    """A customer record on the provider's side. `id` is the provider's
    own customer identifier -- never persisted directly on Organization
    (see app.models.Subscription.provider_reference for where a resulting
    *subscription's* own id is stored instead; a bare customer id with no
    subscription yet has nowhere to live in this schema by design). The
    caller (BillingService.start_checkout) holds this value in memory
    just long enough to pass it straight into create_checkout_session."""

    id: str
    email: str


@dataclass(frozen=True)
class ProviderCheckoutSession:
    """Returned by create_checkout_session -- `url` is where the tenant-
    facing router redirects the organization's browser to actually pay.
    `id` is the provider's own checkout-session identifier, useful for
    logging/support but never persisted (the resulting *subscription*
    reference, delivered later via a checkout_completed webhook event, is
    what gets attached to our Subscription row -- see
    BillingService.attach_provider_subscription)."""

    id: str
    url: str


@dataclass(frozen=True)
class ProviderPortalSession:
    """Returned by create_portal_session -- `url` is where the tenant-
    facing router redirects the organization's browser to reach the
    provider's own hosted billing-management page (Stripe's "Customer
    Portal" and its equivalents on other providers): update a payment
    method, view invoices, change or cancel a plan, all on the provider's
    own UI. This app never renders any of that itself -- see
    app.routers.billing's own module docstring on why no payment UI
    exists in this codebase."""

    url: str


@dataclass(frozen=True)
class ProviderSubscriptionState:
    """The provider's own view of one subscription's current state, as
    returned by retrieve_subscription or carried on a webhook event.
    `status` is the PROVIDER's own status string (e.g. Stripe's "active"/
    "past_due"/"canceled") -- BillingService.sync_from_webhook_event never
    reads it directly for a status transition; it only reads
    current_period_start/end and cancel_at_period_end, which are already
    normalized (real datetimes, a real bool) regardless of provider."""

    provider_reference: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool


@dataclass(frozen=True)
class ProviderWebhookEvent:
    """The normalized result of parse_webhook_event -- the ONLY shape
    app.billing.service.BillingService.sync_from_webhook_event consumes.
    `event_id` is the provider's own event identifier, used by
    app.routers.billing_webhooks for idempotency (see
    app.models.ProviderWebhookReceipt) -- a provider may redeliver the same
    event more than once, and every provider's webhook contract is built
    around the receiver treating that as a safe no-op, never a second
    mutation.

    `metadata` is whatever key/value data the provider echoes back on this
    event -- for a checkout_completed event this is exactly the
    `metadata` dict passed into create_checkout_session
    (CheckoutSessionRequest.metadata), always including `organization_id`
    and `plan_id` (see BillingService.start_checkout); for every other
    event type it's typically empty, since the subscription is looked up
    by provider_reference instead (see
    BillingService.get_subscription_by_provider_reference)."""

    provider_name: str
    event_id: str
    event_type: BillingProviderEventType
    provider_reference: str
    subscription_state: ProviderSubscriptionState | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckoutSessionRequest:
    """Everything create_checkout_session needs, bundled so adding a new
    concrete provider never means changing that method's own signature.
    `metadata` is opaque key/value data round-tripped back on the
    checkout_completed webhook event -- always includes at least
    `organization_id`, set by the caller (see BillingService
    .start_checkout), never by the provider itself."""

    customer_reference: str
    plan: Plan
    billing_period: BillingPeriod
    success_url: str
    cancel_url: str
    metadata: dict[str, str] = field(default_factory=dict)


class BillingProvider(ABC):
    """Provider-agnostic payment-provider interface. Every concrete
    provider (NullBillingProvider, StripeProvider, and any future
    Mercado Pago/Paddle/LemonSqueezy provider) implements every method
    below. `name` is the short, stable identifier stored in
    Subscription.provider_name once a subscription is attached to this
    provider (see BillingService.attach_provider_subscription) -- it must
    never change once a provider ships, since existing Subscription rows
    reference it by value, not by class."""

    name: str

    @abstractmethod
    def create_customer(self, *, organization_id: str, email: str, name: str) -> ProviderCustomer:
        """Creates (or the provider's own equivalent of finding-or-
        creating) a customer record on the provider's side. Called once,
        the first time an organization starts a checkout -- BillingService
        never calls this a second time for an organization that already
        has a provider_reference."""
        raise NotImplementedError

    @abstractmethod
    def create_checkout_session(self, request: CheckoutSessionRequest) -> ProviderCheckoutSession:
        """Starts a hosted checkout flow for the given plan/billing
        period. Must NOT mutate any Subscription row itself -- the
        resulting subscription is only attached to our domain once the
        provider's own checkout_completed webhook event arrives (payment
        may fail, be abandoned, or take a 3-D-Secure round trip, all
        entirely on the provider's own hosted page)."""
        raise NotImplementedError

    @abstractmethod
    def create_portal_session(self, *, customer_reference: str, return_url: str) -> ProviderPortalSession:
        """Starts a hosted billing-management session for an EXISTING
        provider customer (see app.models.ProviderCustomer) -- unlike
        create_checkout_session, this requires the organization to
        already have a provider customer; there is no portal to manage
        billing that doesn't exist yet. `return_url` is where the
        provider's own page sends the browser back once the tenant is
        done."""
        raise NotImplementedError

    @abstractmethod
    def cancel_subscription(self, *, provider_reference: str, at_period_end: bool) -> None:
        """Cancels the provider-side subscription -- immediately if
        `at_period_end` is False, otherwise scheduled for the end of its
        current period. Mirrors BillingService.cancel_immediately/
        cancel_at_period_end's own distinction."""
        raise NotImplementedError

    @abstractmethod
    def reactivate_subscription(self, *, provider_reference: str) -> None:
        """Undoes a scheduled (not-yet-effective) cancellation on the
        provider's side -- mirrors BillingService.reactivate."""
        raise NotImplementedError

    @abstractmethod
    def change_subscription_plan(
        self, *, provider_reference: str, plan: Plan, billing_period: BillingPeriod
    ) -> None:
        """Moves the provider-side subscription onto a different plan/
        billing period (e.g. the provider's own price/item update) --
        the resulting confirmation arrives asynchronously as a
        subscription_updated webhook event, same as any other provider-
        side change; this call only requests it."""
        raise NotImplementedError

    @abstractmethod
    def retrieve_subscription(self, *, provider_reference: str) -> ProviderSubscriptionState:
        """Fetches the provider's current view of one subscription --
        used to reconcile state on demand (e.g. a platform-admin "refresh
        from provider" action), distinct from the push-based webhook flow
        that drives sync_from_webhook_event in the common case."""
        raise NotImplementedError

    @abstractmethod
    def parse_webhook_event(self, *, payload: bytes, signature_header: str) -> ProviderWebhookEvent:
        """Verifies `signature_header` against the configured webhook
        secret and the raw `payload` bytes (never a re-serialized/re-
        parsed version of it -- see app.webhook_signing's own docstring
        on why the exact transmitted bytes must be what gets verified),
        raising InvalidWebhookSignatureError if it doesn't check out.
        Only on success, parses and normalizes the event into a
        ProviderWebhookEvent."""
        raise NotImplementedError
