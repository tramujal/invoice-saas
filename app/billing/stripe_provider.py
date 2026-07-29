"""Stripe (https://stripe.com) BillingProvider implementation -- the
first concrete provider behind app.billing.provider_base.BillingProvider,
built only after that abstraction (and app.billing.service.BillingService's
use of it) already had full test coverage with no Stripe awareness at
all (see tests/billing/fakes.py).

Calls Stripe's REST API directly via `requests` rather than the official
`stripe` Python SDK -- the same choice this codebase already made for
app.ai.anthropic_provider/app.ai.gemini_provider and
app.email.resend_provider ("the only file in the app aware this provider
exists," in resend_provider's own words): the exact request shape stays
fully under our control and doesn't depend on a moving third-party
wrapper, and it keeps `requests` (already a dependency) as the only new
import this integration needs.

This is the ONLY file in the app that knows Stripe's own event names
("checkout.session.completed", etc.), its bracket-notation form encoding,
or its webhook-signature scheme -- everything above
BillingProvider.parse_webhook_event only ever sees the normalized
BillingProviderEventType vocabulary.

Phase 18.1 hardening notes (read before changing _request/_verify_signature):
- Every outbound call has an explicit, short timeout
  (_REQUEST_TIMEOUT_SECONDS) and NO automatic retry of any kind -- no
  urllib3 Retry adapter, no requests.Session, no retry loop. A failed
  call always raises BillingProviderRequestError straight back to the
  caller. This is deliberate: blindly retrying a non-idempotent-by-
  default HTTP call (a customer/subscription create) risks creating a
  duplicate resource on Stripe's side. Safety against a genuine caller-
  level retry (e.g. a user double-clicking "upgrade," or a load balancer
  replaying a request) comes from the Idempotency-Key header every
  mutating call sends instead (see _idempotency_key) -- Stripe itself
  dedupes on that key, which is Stripe's own documented safe-retry
  mechanism, rather than this app guessing at retry logic.
- Every logged/raised error goes through _summarize_error_response,
  which extracts only Stripe's own structured error.type/code/message
  fields (never the raw response body verbatim) -- Stripe error bodies
  can echo back request parameters, and this keeps anything unexpected
  in there out of logs and out of any exception message that might
  reach an HTTP response.
- Neither self._api_key nor self._webhook_secret is ever logged, and
  neither ever appears in a raised exception's message, anywhere in this
  file -- grep for `self._api_key` / `self._webhook_secret` before adding
  a new log line or exception to confirm this still holds.
"""

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from hashlib import sha256

import requests

from app.billing.provider_base import (
    BillingProvider,
    BillingProviderNotConfiguredError,
    BillingProviderRequestError,
    CheckoutSessionRequest,
    InvalidWebhookSignatureError,
    ProviderCheckoutSession,
    ProviderCustomer,
    ProviderPortalSession,
    ProviderSubscriptionState,
    ProviderWebhookEvent,
    UnsupportedWebhookEventError,
)
from app.billing_period import BillingPeriod
from app.models import Plan

logger = logging.getLogger(__name__)

STRIPE_API_BASE = "https://api.stripe.com/v1"

# Explicit, short timeout on every outbound call -- see this module's
# own docstring on why there is deliberately no automatic retry to pair
# with it.
_REQUEST_TIMEOUT_SECONDS = 15

# How far a webhook's own timestamp may drift from wall-clock time before
# it's rejected as a possible replay -- the same 300s Stripe's own
# reference implementation uses by default, and the same technique
# app.webhook_signing (this app's OUTGOING webhook signing) was itself
# modeled on. Overridable per-instance (see StripeProvider.__init__) and
# via STRIPE_WEBHOOK_TOLERANCE_SECONDS (see from_env) for an operator who
# needs a wider window (e.g. known clock drift between this server and
# Stripe) without a code change.
_DEFAULT_SIGNATURE_TOLERANCE_SECONDS = 300

# Maps Stripe's own webhook event-type strings to this app's normalized
# vocabulary -- the one and only place that translation happens.
_EVENT_TYPE_MAP = {
    "checkout.session.completed": "checkout_completed",
    "customer.subscription.updated": "subscription_updated",
    "customer.subscription.deleted": "subscription_canceled",
    "invoice.payment_failed": "payment_failed",
}


def _flatten_params(data: dict, prefix: str = "") -> dict[str, str]:
    """Flattens a nested dict/list into Stripe's own bracket-notation
    form-encoded keys (e.g. {"metadata": {"plan_id": "x"}} becomes
    {"metadata[plan_id]": "x"}; a list becomes index-bracketed keys).
    Stripe's REST API expects exactly this shape for nested parameters
    (line_items, metadata, items) in a form-encoded POST body."""
    flat: dict[str, str] = {}
    for key, value in data.items():
        param_key = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_params(value, param_key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                indexed_key = f"{param_key}[{index}]"
                if isinstance(item, dict):
                    flat.update(_flatten_params(item, indexed_key))
                else:
                    flat[indexed_key] = item
        elif value is not None:
            flat[param_key] = value
    return flat


def _price_id_env_var(plan_code: str, billing_period: BillingPeriod) -> str:
    return f"STRIPE_PRICE_ID__{plan_code.upper()}__{billing_period.value.upper()}"


def _summarize_error_response(response: requests.Response | None) -> str:
    """Extracts only Stripe's own structured error.type/code/message
    fields from an error response -- never the raw response body
    verbatim. Stripe error bodies can echo back request parameters (e.g.
    "customer" validation errors sometimes include the offending value),
    so logging/raising the whole body risks leaking more than intended
    into logs or an HTTP response's detail field. Falls back to a bare,
    fixed string for a non-JSON or unexpectedly-shaped body rather than
    ever including its raw bytes."""
    if response is None:
        return "no response"
    try:
        body = response.json()
        error = body.get("error", {}) if isinstance(body, dict) else {}
        error_type = error.get("type", "unknown_type")
        error_code = error.get("code", "unknown_code")
        error_message = error.get("message", "no message")
        return f"type={error_type} code={error_code} message={error_message}"
    except (ValueError, AttributeError):
        return "non-JSON or unexpected error response body"


def _idempotency_key(*parts: str) -> str:
    """Deterministic Idempotency-Key for an outbound mutating Stripe call
    -- derived from stable identifiers already available to the caller
    (never randomly generated), so repeating the SAME logical request
    (e.g. a user double-clicking "upgrade," a proxy replaying a POST)
    reuses the same key and Stripe safely returns/no-ops on the original
    result instead of creating a second resource. See this module's own
    docstring for why this replaces any notion of automatic retries."""
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def _hour_bucket() -> str:
    """A coarse, deterministic time bucket for create_checkout_session's
    idempotency key -- long enough that a user's repeated clicks within
    the same browsing session collapse onto one checkout session, short
    enough that a genuinely later attempt (Stripe Checkout Sessions
    expire after 24h by default) gets a fresh one instead of being
    permanently pinned to an expired session's id forever."""
    return str(int(time.time()) // 3600)


class StripeProvider(BillingProvider):
    name = "stripe"

    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        api_base: str = STRIPE_API_BASE,
        signature_tolerance_seconds: int = _DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._api_base = api_base
        self._signature_tolerance_seconds = signature_tolerance_seconds

    @classmethod
    def from_env(cls) -> "StripeProvider":
        """Reads STRIPE_API_KEY/STRIPE_WEBHOOK_SECRET (required) and
        STRIPE_WEBHOOK_TOLERANCE_SECONDS (optional, defaults to
        _DEFAULT_SIGNATURE_TOLERANCE_SECONDS) -- called by
        app.billing.provider_factory.get_billing_provider() when
        BILLING_PROVIDER=stripe. Raises BillingProviderNotConfiguredError
        (fail closed) if either required var is missing, rather than
        constructing a provider that would only fail later, on its first
        real call."""
        api_key = os.environ.get("STRIPE_API_KEY")
        webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
        if not api_key or not webhook_secret:
            raise BillingProviderNotConfiguredError(
                "BILLING_PROVIDER=stripe requires both STRIPE_API_KEY and "
                "STRIPE_WEBHOOK_SECRET to be set."
            )
        tolerance_raw = os.environ.get("STRIPE_WEBHOOK_TOLERANCE_SECONDS")
        tolerance = _DEFAULT_SIGNATURE_TOLERANCE_SECONDS
        if tolerance_raw:
            try:
                tolerance = int(tolerance_raw)
            except ValueError:
                logger.warning(
                    "StripeProvider.from_env: STRIPE_WEBHOOK_TOLERANCE_SECONDS=%r is not an "
                    "integer; using the default of %d seconds",
                    tolerance_raw,
                    _DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
                )
        return cls(api_key=api_key, webhook_secret=webhook_secret, signature_tolerance_seconds=tolerance)

    # --- internal HTTP helper -------------------------------------------

    def _request(
        self, method: str, path: str, *, data: dict | None = None, idempotency_key: str | None = None
    ) -> dict:
        url = f"{self._api_base}{path}"
        body = _flatten_params(data) if data else None
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        logger.info("StripeProvider: calling Stripe API method=%s path=%s", method, path)
        try:
            response = requests.request(
                method,
                url,
                data=body,
                headers=headers,
                auth=(self._api_key, ""),
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            error_summary = _summarize_error_response(exc.response)
            logger.exception(
                "StripeProvider: Stripe API returned an HTTP error path=%s status_code=%s error=%s",
                path,
                status_code,
                error_summary,
            )
            raise BillingProviderRequestError(
                f"Stripe API returned {status_code} for {method} {path}: {error_summary}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            # requests' own connection/timeout exceptions describe the
            # network failure itself (DNS, refused, timed out) -- never
            # echo request/response content, so including str(exc)
            # verbatim here (unlike the HTTP-error branch above, which
            # goes through _summarize_error_response) is safe.
            logger.exception("StripeProvider: could not reach Stripe API path=%s", path)
            raise BillingProviderRequestError(f"Could not reach Stripe API: {exc}") from exc
        return response.json()

    def _price_id_for(self, plan: Plan, billing_period: BillingPeriod) -> str:
        env_var = _price_id_env_var(plan.code, billing_period)
        price_id = os.environ.get(env_var)
        if not price_id:
            raise BillingProviderNotConfiguredError(
                f"No Stripe price id configured for plan {plan.code!r} "
                f"({billing_period.value}) -- set {env_var}."
            )
        return price_id

    # --- BillingProvider implementation ----------------------------------

    def create_customer(self, *, organization_id: str, email: str, name: str) -> ProviderCustomer:
        body = self._request(
            "POST",
            "/customers",
            data={"email": email, "name": name, "metadata": {"organization_id": organization_id}},
            idempotency_key=_idempotency_key("create_customer", organization_id),
        )
        return ProviderCustomer(id=body["id"], email=body["email"])

    def create_checkout_session(self, request: CheckoutSessionRequest) -> ProviderCheckoutSession:
        price_id = self._price_id_for(request.plan, request.billing_period)
        organization_id = request.metadata.get("organization_id", request.customer_reference)
        body = self._request(
            "POST",
            "/checkout/sessions",
            data={
                "mode": "subscription",
                "customer": request.customer_reference,
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": request.success_url,
                "cancel_url": request.cancel_url,
                "metadata": request.metadata,
            },
            idempotency_key=_idempotency_key(
                "create_checkout_session", organization_id, price_id, _hour_bucket()
            ),
        )
        return ProviderCheckoutSession(id=body["id"], url=body["url"])

    def create_portal_session(self, *, customer_reference: str, return_url: str) -> ProviderPortalSession:
        body = self._request(
            "POST",
            "/billing_portal/sessions",
            data={"customer": customer_reference, "return_url": return_url},
            idempotency_key=_idempotency_key("create_portal_session", customer_reference, _hour_bucket()),
        )
        return ProviderPortalSession(url=body["url"])

    def cancel_subscription(self, *, provider_reference: str, at_period_end: bool) -> None:
        if at_period_end:
            self._request(
                "POST",
                f"/subscriptions/{provider_reference}",
                data={"cancel_at_period_end": "true"},
                idempotency_key=_idempotency_key("cancel_subscription", provider_reference, "at_period_end"),
            )
        else:
            self._request(
                "DELETE",
                f"/subscriptions/{provider_reference}",
                idempotency_key=_idempotency_key("cancel_subscription", provider_reference, "immediate"),
            )

    def reactivate_subscription(self, *, provider_reference: str) -> None:
        self._request(
            "POST",
            f"/subscriptions/{provider_reference}",
            data={"cancel_at_period_end": "false"},
            idempotency_key=_idempotency_key("reactivate_subscription", provider_reference),
        )

    def change_subscription_plan(
        self, *, provider_reference: str, plan: Plan, billing_period: BillingPeriod
    ) -> None:
        price_id = self._price_id_for(plan, billing_period)
        # GET is naturally idempotent (read-only) -- no Idempotency-Key needed.
        current = self._request("GET", f"/subscriptions/{provider_reference}")
        item_id = current["items"]["data"][0]["id"]
        self._request(
            "POST",
            f"/subscriptions/{provider_reference}",
            data={"items": [{"id": item_id, "price": price_id}]},
            idempotency_key=_idempotency_key("change_subscription_plan", provider_reference, price_id),
        )

    def retrieve_subscription(self, *, provider_reference: str) -> ProviderSubscriptionState:
        body = self._request("GET", f"/subscriptions/{provider_reference}")
        return self._to_subscription_state(body)

    def _to_subscription_state(self, stripe_subscription: dict) -> ProviderSubscriptionState:
        return ProviderSubscriptionState(
            provider_reference=stripe_subscription["id"],
            status=stripe_subscription["status"],
            current_period_start=datetime.fromtimestamp(
                stripe_subscription["current_period_start"], tz=timezone.utc
            ),
            current_period_end=datetime.fromtimestamp(
                stripe_subscription["current_period_end"], tz=timezone.utc
            ),
            cancel_at_period_end=bool(stripe_subscription["cancel_at_period_end"]),
        )

    def parse_webhook_event(self, *, payload: bytes, signature_header: str) -> ProviderWebhookEvent:
        self._verify_signature(payload=payload, signature_header=signature_header)
        body = json.loads(payload)

        stripe_event_type = body["type"]
        normalized_type = _EVENT_TYPE_MAP.get(stripe_event_type)
        if normalized_type is None:
            raise UnsupportedWebhookEventError(
                f"Stripe event type {stripe_event_type!r} has no handler"
            )
        # Deferred import: BillingProviderEventType is a plain enum with
        # no provider awareness, but importing it at module load time
        # alongside everything else here would blur the "this file is
        # the translation boundary" intent -- kept local to make that
        # boundary visually obvious at the one line it actually happens.
        from app.billing.provider_base import BillingProviderEventType

        event_type = BillingProviderEventType(normalized_type)
        stripe_object = body["data"]["object"]

        if event_type == BillingProviderEventType.checkout_completed:
            provider_reference = stripe_object["subscription"]
            metadata = stripe_object.get("metadata") or {}
            subscription_state = None
        elif event_type == BillingProviderEventType.payment_failed:
            provider_reference = stripe_object["subscription"]
            metadata = {}
            subscription_state = None
        elif event_type == BillingProviderEventType.subscription_updated:
            # The only event type BillingService.sync_from_webhook_event
            # actually reads subscription_state for (see
            # sync_period_from_provider) -- subscription_canceled below
            # only needs provider_reference, so it doesn't require every
            # period field to be present on the payload.
            provider_reference = stripe_object["id"]
            metadata = {}
            subscription_state = self._to_subscription_state(stripe_object)
        else:
            provider_reference = stripe_object["id"]
            metadata = {}
            subscription_state = None

        return ProviderWebhookEvent(
            provider_name=self.name,
            event_id=body["id"],
            event_type=event_type,
            provider_reference=provider_reference,
            subscription_state=subscription_state,
            metadata=metadata,
        )

    def _verify_signature(self, *, payload: bytes, signature_header: str) -> None:
        """Verifies Stripe's own "Stripe-Signature" header format:
        "t=<unix timestamp>,v1=<hex hmac>[,v1=<hex hmac>...][,v0=...]" --
        each v1 value computed as hmac_sha256(webhook_secret,
        f"{t}.{payload}"). Plain hmac/hashlib, no SDK -- the exact
        technique app.webhook_signing already uses for this app's own
        outgoing webhooks (itself modeled on this same Stripe scheme, per
        that module's own docstring).

        Stripe's header can carry MORE THAN ONE v1= entry during a
        webhook signing-secret rotation (Stripe signs the same payload
        with both the old and new secret for a transition period) --
        verification must accept the payload if it matches ANY v1 value,
        not just whichever one a naive single-value parse happens to
        keep (the previous implementation here used a dict keyed by
        element name, which silently discarded every v1 but the last one
        parsed -- this fixes that).

        The payload's own bytes (never a re-serialized/re-parsed version)
        are what's verified -- see the raw `payload: bytes` parameter and
        app.routers.billing_webhooks, which reads `await request.body()`
        and passes it straight through with no intermediate JSON
        round-trip. Replay protection beyond this method's own tolerance-
        window check happens one layer up, via
        app.models.ProviderWebhookReceipt (see
        app.routers.billing_webhooks) -- a redelivered event with a
        still-valid, still-in-tolerance signature is rejected there, not
        here, since this method's only job is "is this payload
        authentically from Stripe," not "have we already processed it."
        """
        timestamp_str: str | None = None
        signatures: list[str] = []
        for element in signature_header.split(","):
            if "=" not in element:
                continue
            key, _, value = element.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "t":
                timestamp_str = value
            elif key == "v1":
                signatures.append(value)

        if not timestamp_str or not signatures:
            raise InvalidWebhookSignatureError("Stripe-Signature header is missing t= or v1=")

        try:
            timestamp = int(timestamp_str)
        except ValueError as exc:
            raise InvalidWebhookSignatureError("Stripe-Signature header has a non-numeric t=") from exc

        if abs(time.time() - timestamp) > self._signature_tolerance_seconds:
            raise InvalidWebhookSignatureError("Stripe-Signature timestamp is outside the tolerance window")

        signed_payload = f"{timestamp}.".encode("ascii") + payload
        expected_signature = hmac.new(self._webhook_secret.encode("utf-8"), signed_payload, sha256).hexdigest()
        # Constant-time comparison against every provided v1 value --
        # matching ANY one of them is a valid signature (rotation
        # window). hmac.compare_digest is still used for each individual
        # comparison; looping over a small, fixed-size list (Stripe never
        # sends more than a couple during rotation) doesn't reintroduce a
        # meaningful timing side-channel.
        if not any(hmac.compare_digest(expected_signature, candidate) for candidate in signatures):
            raise InvalidWebhookSignatureError("Stripe-Signature signature does not match")
