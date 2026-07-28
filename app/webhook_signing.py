"""Webhook signing-secret generation and HMAC request signing.

Secret format: "whsec_{43 URL-safe base64 characters}" (secrets.token_urlsafe(32),
256 bits) -- a static, human-recognizable prefix exactly like app.api_keys's
"sk_" (a leaked value is immediately identifiable as a webhook secret, never
confused with an API key or a password).

Unlike app.api_keys (an INBOUND credential, verified only by comparing a
freshly-computed hash against a stored one), this secret is used to
COMPUTE a fresh HMAC signature on every OUTBOUND delivery, forever -- so
it cannot be one-way hashed the way an API key secret is. See
WebhookEndpoint.secret's own docstring in app/models.py for the full
rationale and the residual-risk statement this implies.

Canonical signed string: "{timestamp}.{raw_body}" -- including the Unix
timestamp (not just the body) is what lets a receiver reject a replayed-
but-otherwise-valid signature outside a small tolerance window, the same
technique Stripe's own webhook signing uses. `raw_body` must be the exact
bytes actually transmitted -- signing a re-serialized dict would let a
proxy or logging step subtly re-encode the JSON (key order, whitespace)
and silently invalidate every signature, so callers always sign the same
bytes object they send.
"""

import hmac
import secrets
from hashlib import sha256

SECRET_SCHEME = "whsec"
_SECRET_BYTES = 32  # 256 bits, matches app.api_keys._SECRET_BYTES

SIGNATURE_HEADER = "X-Webhook-Signature"
EVENT_HEADER = "X-Webhook-Event"
DELIVERY_ID_HEADER = "X-Webhook-Delivery"
TIMESTAMP_HEADER = "X-Webhook-Timestamp"


def generate_webhook_secret() -> str:
    return f"{SECRET_SCHEME}_{secrets.token_urlsafe(_SECRET_BYTES)}"


def build_signed_headers(
    *, secret: str, event_type: str, delivery_id: str, timestamp: int, body: bytes
) -> dict[str, str]:
    """Computes the full set of signature-related headers for one delivery
    attempt. `timestamp` is passed in (rather than computed here) so a
    caller can log/persist the exact value that was signed."""
    signed_string = f"{timestamp}.".encode("ascii") + body
    signature = hmac.new(secret.encode("utf-8"), signed_string, sha256).hexdigest()
    return {
        SIGNATURE_HEADER: f"t={timestamp},v1={signature}",
        EVENT_HEADER: event_type,
        DELIVERY_ID_HEADER: delivery_id,
        TIMESTAMP_HEADER: str(timestamp),
    }
