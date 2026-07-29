"""Tests for app.billing.stripe_provider.StripeProvider -- the first
concrete BillingProvider implementation. Every Stripe REST call is
mocked (monkeypatching requests.request, same convention
tests/test_webhooks.py already uses for its own outgoing-webhook
delivery tests) -- no real network call, no real Stripe account needed.

Signature verification tests compute their own HMAC independently of
StripeProvider's implementation (not by importing its private method),
so a bug in _verify_signature can't hide behind a test that only checks
consistency with itself.
"""

import hmac
import json
import time
from hashlib import sha256

import pytest
import requests

from app.billing.provider_base import (
    BillingProviderEventType,
    BillingProviderNotConfiguredError,
    BillingProviderRequestError,
    CheckoutSessionRequest,
    InvalidWebhookSignatureError,
    UnsupportedWebhookEventError,
)
from app.billing.stripe_provider import StripeProvider
from app.billing_period import BillingPeriod
from tests.factories import make_plan

WEBHOOK_SECRET = "whsec_test_secret"


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict):
        self.status_code = status_code
        self._json_body = json_body
        self.content = json.dumps(json_body).encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def json(self):
        return self._json_body


@pytest.fixture
def provider() -> StripeProvider:
    return StripeProvider(api_key="sk_test_fake", webhook_secret=WEBHOOK_SECRET)


def _sign(secret: str, timestamp: int, payload: bytes) -> str:
    signed_payload = f"{timestamp}.".encode("ascii") + payload
    return hmac.new(secret.encode("utf-8"), signed_payload, sha256).hexdigest()


# --- from_env --------------------------------------------------------------


def test_from_env_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    with pytest.raises(BillingProviderNotConfiguredError):
        StripeProvider.from_env()


def test_from_env_succeeds_when_configured(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    resolved = StripeProvider.from_env()
    assert isinstance(resolved, StripeProvider)
    assert resolved.name == "stripe"


# --- create_customer ---------------------------------------------------


def test_create_customer_calls_stripe_and_returns_customer(monkeypatch, provider):
    captured = {}

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        captured.update(method=method, url=url, data=data, auth=auth)
        return _FakeResponse(200, {"id": "cus_123", "email": "owner@example.com"})

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)

    customer = provider.create_customer(
        organization_id="org-1", email="owner@example.com", name="Acme Inc"
    )

    assert customer.id == "cus_123"
    assert customer.email == "owner@example.com"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/customers")
    assert captured["data"]["metadata[organization_id]"] == "org-1"
    assert captured["auth"] == ("sk_test_fake", "")


# --- idempotency keys -------------------------------------------------------


def test_create_customer_sends_a_stable_idempotency_key_for_the_same_org(monkeypatch, provider):
    captured_keys = []

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        captured_keys.append((headers or {}).get("Idempotency-Key"))
        return _FakeResponse(200, {"id": "cus_123", "email": "owner@example.com"})

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)

    provider.create_customer(organization_id="org-1", email="a@example.com", name="a")
    provider.create_customer(organization_id="org-1", email="a@example.com", name="a")
    provider.create_customer(organization_id="org-2", email="b@example.com", name="b")

    assert captured_keys[0] is not None
    assert captured_keys[0] == captured_keys[1]  # same org -> same key
    assert captured_keys[2] != captured_keys[0]  # different org -> different key


def test_cancel_subscription_uses_different_keys_for_immediate_vs_at_period_end(monkeypatch, provider):
    captured_keys = []

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        captured_keys.append((headers or {}).get("Idempotency-Key"))
        return _FakeResponse(200, {"id": "sub_1"})

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)

    provider.cancel_subscription(provider_reference="sub_1", at_period_end=False)
    provider.cancel_subscription(provider_reference="sub_1", at_period_end=True)

    assert all(captured_keys)
    assert captured_keys[0] != captured_keys[1]


def test_get_requests_never_send_an_idempotency_key(monkeypatch, provider):
    captured_headers = []

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        captured_headers.append(headers)
        return _FakeResponse(
            200,
            {
                "id": "sub_1",
                "status": "active",
                "current_period_start": 1735689600,
                "current_period_end": 1738368000,
                "cancel_at_period_end": False,
            },
        )

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)
    provider.retrieve_subscription(provider_reference="sub_1")

    assert captured_headers == [None]


# --- create_checkout_session --------------------------------------------


def test_create_checkout_session_uses_price_id_from_env(monkeypatch, db_session, provider):
    plan = make_plan(db_session, code="stripe-plan", sort_order=1)
    # Plan codes can contain hyphens; the env var name upper-cases the
    # code verbatim (no character substitution) -- set the exact var
    # StripeProvider actually looks up.
    monkeypatch.setenv("STRIPE_PRICE_ID__STRIPE-PLAN__MONTHLY", "price_abc")

    captured = {}

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        captured.update(method=method, url=url, data=data)
        return _FakeResponse(200, {"id": "cs_123", "url": "https://checkout.stripe.com/session/cs_123"})

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)

    session = provider.create_checkout_session(
        CheckoutSessionRequest(
            customer_reference="cus_123",
            plan=plan,
            billing_period=BillingPeriod.monthly,
            success_url="https://app.test/success",
            cancel_url="https://app.test/cancel",
            metadata={"organization_id": "org-1", "plan_id": plan.id, "billing_period": "monthly"},
        )
    )

    assert session.id == "cs_123"
    assert session.url == "https://checkout.stripe.com/session/cs_123"
    assert captured["data"]["line_items[0][price]"] == "price_abc"
    assert captured["data"]["line_items[0][quantity]"] == 1
    assert captured["data"]["metadata[organization_id]"] == "org-1"


def test_create_checkout_session_raises_when_price_id_not_configured(monkeypatch, db_session, provider):
    plan = make_plan(db_session, code="unconfigured-plan", sort_order=1)
    monkeypatch.delenv("STRIPE_PRICE_ID__UNCONFIGURED-PLAN__MONTHLY", raising=False)

    with pytest.raises(BillingProviderNotConfiguredError):
        provider.create_checkout_session(
            CheckoutSessionRequest(
                customer_reference="cus_123",
                plan=plan,
                billing_period=BillingPeriod.monthly,
                success_url="https://app.test/success",
                cancel_url="https://app.test/cancel",
            )
        )


# --- cancel / reactivate -------------------------------------------------


def test_cancel_subscription_immediate_calls_delete(monkeypatch, provider):
    captured = {}

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        captured.update(method=method, url=url)
        return _FakeResponse(200, {"id": "sub_1", "status": "canceled"})

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)
    provider.cancel_subscription(provider_reference="sub_1", at_period_end=False)

    assert captured["method"] == "DELETE"
    assert captured["url"].endswith("/subscriptions/sub_1")


def test_cancel_subscription_at_period_end_calls_post_with_flag(monkeypatch, provider):
    captured = {}

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        captured.update(method=method, url=url, data=data)
        return _FakeResponse(200, {"id": "sub_1"})

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)
    provider.cancel_subscription(provider_reference="sub_1", at_period_end=True)

    assert captured["method"] == "POST"
    assert captured["data"]["cancel_at_period_end"] == "true"


# --- retrieve_subscription -----------------------------------------------


def test_retrieve_subscription_converts_timestamps(monkeypatch, provider):
    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        return _FakeResponse(
            200,
            {
                "id": "sub_1",
                "status": "active",
                "current_period_start": 1735689600,  # 2025-01-01T00:00:00Z
                "current_period_end": 1738368000,  # 2025-02-01T00:00:00Z
                "cancel_at_period_end": False,
            },
        )

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)
    state = provider.retrieve_subscription(provider_reference="sub_1")

    assert state.provider_reference == "sub_1"
    assert state.status == "active"
    assert state.current_period_start.year == 2025
    assert state.cancel_at_period_end is False


# --- HTTP error mapping ---------------------------------------------------


def test_http_error_response_is_wrapped(monkeypatch, provider):
    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        return _FakeResponse(402, {"error": {"message": "card declined"}})

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)
    with pytest.raises(BillingProviderRequestError):
        provider.retrieve_subscription(provider_reference="sub_1")


def test_http_error_message_is_sanitized_never_raw_body(monkeypatch, provider):
    """The raised exception's message must come from
    _summarize_error_response's structured type/code/message extraction,
    never the raw response body -- proven here by including a field in
    the raw body that must NOT survive into the exception message."""

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        return _FakeResponse(
            402,
            {
                "error": {
                    "type": "card_error",
                    "code": "card_declined",
                    "message": "Your card was declined.",
                    "param": "customer[email]=someone@example.com",  # must not leak
                }
            },
        )

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)
    with pytest.raises(BillingProviderRequestError) as exc_info:
        provider.retrieve_subscription(provider_reference="sub_1")

    message = str(exc_info.value)
    assert "type=card_error" in message
    assert "code=card_declined" in message
    assert "Your card was declined." in message
    assert "someone@example.com" not in message


def test_http_error_with_non_json_body_falls_back_to_a_generic_message(monkeypatch, provider):
    class _NonJsonResponse(_FakeResponse):
        def json(self):
            raise ValueError("not JSON")

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        response = _NonJsonResponse(500, {})
        response.content = b"<html>Internal Server Error</html>"
        return response

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)
    with pytest.raises(BillingProviderRequestError) as exc_info:
        provider.retrieve_subscription(provider_reference="sub_1")

    assert "<html>" not in str(exc_info.value)


def test_connection_error_is_wrapped(monkeypatch, provider):
    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)
    with pytest.raises(BillingProviderRequestError):
        provider.retrieve_subscription(provider_reference="sub_1")


# --- webhook signature verification ---------------------------------------


def test_parse_webhook_event_accepts_a_validly_signed_payload(provider):
    payload = json.dumps(
        {
            "id": "evt_1",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_1", "status": "canceled"}},
        }
    ).encode("utf-8")
    timestamp = int(time.time())
    signature = _sign(WEBHOOK_SECRET, timestamp, payload)
    header = f"t={timestamp},v1={signature}"

    event = provider.parse_webhook_event(payload=payload, signature_header=header)
    assert event.event_type == BillingProviderEventType.subscription_canceled
    assert event.provider_reference == "sub_1"
    assert event.provider_name == "stripe"


def test_parse_webhook_event_rejects_wrong_signature(provider):
    payload = b'{"id":"evt_1","type":"customer.subscription.deleted","data":{"object":{"id":"sub_1"}}}'
    timestamp = int(time.time())
    header = f"t={timestamp},v1=deadbeef"

    with pytest.raises(InvalidWebhookSignatureError):
        provider.parse_webhook_event(payload=payload, signature_header=header)


def test_parse_webhook_event_rejects_expired_timestamp(provider):
    payload = b'{"id":"evt_1","type":"customer.subscription.deleted","data":{"object":{"id":"sub_1"}}}'
    old_timestamp = int(time.time()) - 10_000
    signature = _sign(WEBHOOK_SECRET, old_timestamp, payload)
    header = f"t={old_timestamp},v1={signature}"

    with pytest.raises(InvalidWebhookSignatureError):
        provider.parse_webhook_event(payload=payload, signature_header=header)


def test_parse_webhook_event_rejects_malformed_header(provider):
    payload = b"{}"
    with pytest.raises(InvalidWebhookSignatureError):
        provider.parse_webhook_event(payload=payload, signature_header="not-a-valid-header")


def test_parse_webhook_event_raises_for_unsupported_event_type(provider):
    payload = json.dumps({"id": "evt_1", "type": "charge.succeeded", "data": {"object": {}}}).encode(
        "utf-8"
    )
    timestamp = int(time.time())
    signature = _sign(WEBHOOK_SECRET, timestamp, payload)
    header = f"t={timestamp},v1={signature}"

    with pytest.raises(UnsupportedWebhookEventError):
        provider.parse_webhook_event(payload=payload, signature_header=header)


def test_parse_webhook_event_checkout_completed_extracts_metadata(provider):
    payload = json.dumps(
        {
            "id": "evt_checkout_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "subscription": "sub_new_1",
                    "metadata": {"organization_id": "org-1", "plan_id": "plan-1", "billing_period": "yearly"},
                }
            },
        }
    ).encode("utf-8")
    timestamp = int(time.time())
    signature = _sign(WEBHOOK_SECRET, timestamp, payload)
    header = f"t={timestamp},v1={signature}"

    event = provider.parse_webhook_event(payload=payload, signature_header=header)
    assert event.event_type == BillingProviderEventType.checkout_completed
    assert event.provider_reference == "sub_new_1"
    assert event.metadata == {"organization_id": "org-1", "plan_id": "plan-1", "billing_period": "yearly"}


def test_parse_webhook_event_subscription_updated_includes_state(provider):
    payload = json.dumps(
        {
            "id": "evt_update_1",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_1",
                    "status": "active",
                    "current_period_start": 1735689600,
                    "current_period_end": 1738368000,
                    "cancel_at_period_end": True,
                }
            },
        }
    ).encode("utf-8")
    timestamp = int(time.time())
    signature = _sign(WEBHOOK_SECRET, timestamp, payload)
    header = f"t={timestamp},v1={signature}"

    event = provider.parse_webhook_event(payload=payload, signature_header=header)
    assert event.event_type == BillingProviderEventType.subscription_updated
    assert event.subscription_state is not None
    assert event.subscription_state.cancel_at_period_end is True


# --- multiple v1 signatures (secret rotation) + configurable tolerance -----


def test_parse_webhook_event_accepts_a_second_v1_signature_during_secret_rotation(provider):
    """Stripe signs the same payload with both the old and new secret
    during a webhook signing-secret rotation, sending multiple v1=
    entries in one header. Verification must accept the payload if it
    matches ANY of them -- here, the first v1 is signed with a stale
    secret (must NOT verify alone) and the second with the provider's
    real secret."""
    payload = b'{"id":"evt_rotation_1","type":"customer.subscription.deleted","data":{"object":{"id":"sub_1"}}}'
    timestamp = int(time.time())
    stale_signature = _sign("whsec_stale_secret", timestamp, payload)
    real_signature = _sign(WEBHOOK_SECRET, timestamp, payload)
    header = f"t={timestamp},v1={stale_signature},v1={real_signature}"

    event = provider.parse_webhook_event(payload=payload, signature_header=header)
    assert event.event_id == "evt_rotation_1"


def test_parse_webhook_event_rejects_when_no_v1_signature_matches(provider):
    payload = b'{"id":"evt_1","type":"customer.subscription.deleted","data":{"object":{"id":"sub_1"}}}'
    timestamp = int(time.time())
    stale_signature = _sign("whsec_stale_secret", timestamp, payload)
    other_stale_signature = _sign("whsec_another_stale_secret", timestamp, payload)
    header = f"t={timestamp},v1={stale_signature},v1={other_stale_signature}"

    with pytest.raises(InvalidWebhookSignatureError):
        provider.parse_webhook_event(payload=payload, signature_header=header)


def test_signature_tolerance_is_configurable_via_constructor(monkeypatch):
    """A provider configured with a narrower tolerance rejects a payload
    an otherwise-identical default-tolerance provider would accept."""
    payload = b'{"id":"evt_1","type":"customer.subscription.deleted","data":{"object":{"id":"sub_1"}}}'
    timestamp = int(time.time()) - 60  # 60 seconds old
    signature = _sign(WEBHOOK_SECRET, timestamp, payload)
    header = f"t={timestamp},v1={signature}"

    narrow_provider = StripeProvider(
        api_key="sk_test_fake", webhook_secret=WEBHOOK_SECRET, signature_tolerance_seconds=30
    )
    with pytest.raises(InvalidWebhookSignatureError):
        narrow_provider.parse_webhook_event(payload=payload, signature_header=header)

    wide_provider = StripeProvider(
        api_key="sk_test_fake", webhook_secret=WEBHOOK_SECRET, signature_tolerance_seconds=300
    )
    event = wide_provider.parse_webhook_event(payload=payload, signature_header=header)
    assert event.event_id == "evt_1"


def test_from_env_reads_tolerance_override(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "60")

    resolved = StripeProvider.from_env()

    assert resolved._signature_tolerance_seconds == 60


def test_from_env_falls_back_to_default_tolerance_on_invalid_override(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "not-a-number")

    resolved = StripeProvider.from_env()

    assert resolved._signature_tolerance_seconds == 300


# --- create_portal_session ---------------------------------------------


def test_create_portal_session_calls_stripe_and_returns_url(monkeypatch, provider):
    captured = {}

    def fake_request(method, url, data=None, headers=None, auth=None, timeout=None):
        captured.update(method=method, url=url, data=data, headers=headers)
        return _FakeResponse(200, {"url": "https://billing.stripe.com/session/abc"})

    monkeypatch.setattr("app.billing.stripe_provider.requests.request", fake_request)

    session = provider.create_portal_session(
        customer_reference="cus_123", return_url="https://app.test/settings/plan"
    )

    assert session.url == "https://billing.stripe.com/session/abc"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/billing_portal/sessions")
    assert captured["data"]["customer"] == "cus_123"
    assert captured["data"]["return_url"] == "https://app.test/settings/plan"
    assert captured["headers"]["Idempotency-Key"]
