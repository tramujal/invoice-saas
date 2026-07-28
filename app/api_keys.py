"""Organization API key format, generation, and hashing.

Mirrors app.tokens's own rationale exactly (SHA-256, not bcrypt, for a
high-entropy random secret -- see that module's docstring) but adds one
thing app.tokens's single-opaque-token shape doesn't have: a plaintext,
indexed *prefix* segment so a key can be looked up in O(1) without
hashing and comparing against every row in the table -- the same
lookup-key/secret split Stripe, GitHub, and OpenAI all use.

Full key shape: "sk_{prefix}_{secret}"
  - "sk_" is a static, human-recognizable marker (a leaked key is
    immediately identifiable as this app's format in a scan/grep, and
    distinguishable from a JWT or a password at a glance).
  - {prefix} is 12 URL-safe characters, stored in plaintext in an
    indexed unique column -- purely a lookup key, never treated as a
    secret on its own; the hashed {secret} portion is always checked
    too, so knowing only the prefix (e.g. from a log line) grants
    nothing.
  - {secret} is a 256-bit random token (secrets.token_urlsafe(32));
    only its SHA-256 hash is ever persisted. The complete key is shown
    to the caller exactly once, at creation/rotation time, and is never
    recoverable afterward -- there is no "reveal" endpoint.
"""

import hmac
import secrets

from app.tokens import hash_token

KEY_SCHEME = "sk"
_PREFIX_BYTES = 9  # secrets.token_urlsafe(9) -> always exactly 12 URL-safe base64 characters
_PREFIX_LENGTH = 12
_SECRET_BYTES = 32  # 256 bits, matches app.tokens._TOKEN_BYTES
_SCHEME_HEADER = f"{KEY_SCHEME}_"


class InvalidApiKeyFormatError(Exception):
    """The given string isn't shaped like sk_<prefix>_<secret> at all --
    raised before any DB lookup is attempted, so a malformed
    Authorization header never even reaches a query."""


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, hashed_secret). full_key must be shown
    to the caller exactly once by whoever calls this; only prefix
    (plaintext) and hashed_secret are ever persisted."""
    prefix = secrets.token_urlsafe(_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    full_key = f"{KEY_SCHEME}_{prefix}_{secret}"
    return full_key, prefix, hash_token(secret)


def parse_api_key(full_key: str) -> tuple[str, str]:
    """Splits a presented key into (prefix, secret) for lookup +
    verification. Raises InvalidApiKeyFormatError for anything not
    shaped like this app's own key format.

    Deliberately does NOT split on "_" (naively splitting on the first
    two underscores): secrets.token_urlsafe's own alphabet includes "_",
    so either the prefix or the secret can legitimately contain one,
    which would silently misparse a valid key. The prefix has a fixed,
    known length instead (see _PREFIX_LENGTH), so it's sliced by
    position, never split by delimiter."""
    if not full_key.startswith(_SCHEME_HEADER):
        raise InvalidApiKeyFormatError(full_key)
    rest = full_key[len(_SCHEME_HEADER):]
    if len(rest) <= _PREFIX_LENGTH + 1 or rest[_PREFIX_LENGTH] != "_":
        raise InvalidApiKeyFormatError(full_key)
    prefix = rest[:_PREFIX_LENGTH]
    secret = rest[_PREFIX_LENGTH + 1 :]
    if not prefix or not secret:
        raise InvalidApiKeyFormatError(full_key)
    return prefix, secret


def verify_api_key_secret(secret: str, stored_hash: str) -> bool:
    """Constant-time verification -- same rationale as
    app.tokens.tokens_match: defense in depth on top of the exact-match
    prefix lookup used to find the candidate row in the first place."""
    return hmac.compare_digest(hash_token(secret), stored_hash)
