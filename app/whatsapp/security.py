"""Phone normalization, one-time verification codes, and bridge<->backend
HMAC request signing for the experimental WhatsApp assistant (Phase 23).

The signing scheme mirrors app.billing.stripe_provider's
_verify_signature/app.webhook_signing's build_signed_headers exactly --
same canonical string ("{timestamp}.{raw_body}"), same "t=<ts>,v1=<hex>"
header shape, same hmac.compare_digest constant-time comparison, same
tolerance-window replay protection. This module exists separately from
app.webhook_signing because that one is specific to outbound webhook
*deliveries* (it bakes in event_type/delivery_id headers); the bridge
needs the same primitive in BOTH directions (the backend signs requests
it sends to the bridge; the backend verifies requests the bridge sends
back) with no delivery/event concept at all.
"""

import hashlib
import hmac
import re
import secrets
import time
from hashlib import sha256

SIGNATURE_HEADER = "X-WhatsApp-Bridge-Signature"

_VERIFICATION_CODE_LENGTH = 6


class InvalidBridgeSignatureError(Exception):
    """Raised when a request's signature doesn't verify -- callers
    (app.routers.whatsapp_bridge) turn this into a 401, never leaking
    which specific check failed (missing header vs. bad timestamp vs.
    bad signature) in the response body."""


def sign_bridge_request(*, secret: str, timestamp: int, body: bytes) -> str:
    """Returns the "t=<ts>,v1=<hex>" header value for one request --
    used both when this app signs an outbound call to the bridge and
    when the bridge signs an inbound call to this app (the bridge
    implements the identical scheme in TypeScript, see
    whatsapp-bridge/src/security/request-signing.ts)."""
    signed_string = f"{timestamp}.".encode("ascii") + body
    signature = hmac.new(secret.encode("utf-8"), signed_string, sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def verify_bridge_signature(
    *, secret: str, signature_header: str, body: bytes, tolerance_seconds: int
) -> None:
    """Raises InvalidBridgeSignatureError if `signature_header` doesn't
    verify against `body` using `secret` within `tolerance_seconds` of
    wall-clock time. Mirrors app.billing.stripe_provider._verify_signature
    exactly: parses every v1= candidate (never just the last one, for a
    secret-rotation window), checks the timestamp tolerance BEFORE the
    signature (cheaper check first), and compares every candidate with
    hmac.compare_digest, never `==`."""
    if not signature_header:
        raise InvalidBridgeSignatureError("Missing signature header.")

    timestamp: int | None = None
    signatures: list[str] = []
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                raise InvalidBridgeSignatureError("Malformed timestamp in signature header.")
        elif key == "v1":
            signatures.append(value)

    if timestamp is None or not signatures:
        raise InvalidBridgeSignatureError("Malformed signature header.")

    if abs(time.time() - timestamp) > tolerance_seconds:
        raise InvalidBridgeSignatureError("Signature timestamp is outside the tolerance window.")

    signed_string = f"{timestamp}.".encode("ascii") + body
    expected = hmac.new(secret.encode("utf-8"), signed_string, sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise InvalidBridgeSignatureError("Signature does not match.")


# Everything except digits and a leading '+' is pure formatting, plus a
# WhatsApp JID suffix (whatsapp-web.js identifies chats as e.g.
# "59899123456@c.us") which carries no phone-number meaning of its own --
# stripped the same way app.customer_validation.normalize_customer_phone
# strips punctuation, for the same "compare on the meaningful part only"
# reason. A leading "00" international prefix folds to "+", matching that
# same module's convention exactly (never inferring a missing country
# code -- see that function's own docstring for why).
_JID_SUFFIX_RE = re.compile(r"@.*$")
_PHONE_PUNCTUATION_RE = re.compile(r"[^\d+]")


def normalize_phone_number(raw: str) -> str:
    """The single normalization function every WhatsAppIdentity lookup/
    comparison goes through -- never re-implemented at a second call
    site. Always includes a leading '+' in the result (unlike
    app.customer_validation.normalize_customer_phone, which leaves an
    unprefixed number as-is): a WhatsApp identity is always a real,
    reachable international number, so requiring the '+' catches an
    obviously-incomplete number at link time rather than silently
    accepting one no message could ever be routed to."""
    without_jid = _JID_SUFFIX_RE.sub("", raw.strip())
    stripped = _PHONE_PUNCTUATION_RE.sub("", without_jid)
    if stripped.startswith("00"):
        stripped = "+" + stripped[2:]
    if stripped and not stripped.startswith("+"):
        stripped = "+" + stripped
    return stripped


def generate_verification_code() -> str:
    """A short, human-typable one-time code (WhatsApp linking, section 5
    of the phase spec) -- deliberately NOT a high-entropy token like
    app.tokens.generate_token: the user has to read this on a screen and
    type it into WhatsApp by hand, so it must stay short. Low entropy
    (1 in 1,000,000) is why this is paired with a short TTL and a capped
    attempt count (see app.whatsapp.service) rather than relied on alone,
    the same defense-in-depth shape a numeric 2FA/OTP code always uses."""
    return f"{secrets.randbelow(1_000_000):0{_VERIFICATION_CODE_LENGTH}d}"


def hash_verification_code(code: str) -> str:
    """Fast hash (not bcrypt) is correct here for the same reason
    app.tokens uses SHA-256 for password-reset tokens: the code is never
    persisted raw, and brute-forcing a 6-digit space is instead mitigated
    by the short TTL + capped attempt count, not by hash slowness."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verification_code_matches(raw_code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_verification_code(raw_code.strip()), stored_hash)
