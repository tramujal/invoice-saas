"""Shared primitives for one-time, revocable tokens (password reset, email
verification, and any future feature needing the same shape).

These are high-entropy random strings, not JWTs: a JWT's whole point is
being statelessly verifiable, which is the opposite of what a one-time,
revocable link needs (we must be able to mark one used or invalidate it
early, which requires a DB row to flip).

Tokens are hashed with a fast cryptographic hash (SHA-256), not bcrypt.
bcrypt's deliberate slowness exists to resist brute-forcing low-entropy,
human-chosen secrets (passwords). A 256-bit random token from `secrets` is
already computationally infeasible to guess, so a fast hash is both correct
and appropriate here — bcrypt would only add latency with no security
benefit.

Feature-specific modules (app/password_reset.py, app/email_verification.py)
import these primitives and add only what actually differs between
features: TTL and link path.
"""

import hashlib
import hmac
import os
import secrets

_TOKEN_BYTES = 32  # 256 bits of entropy

FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def generate_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def tokens_match(raw_token: str, stored_hash: str) -> bool:
    """Constant-time comparison between a freshly-hashed candidate token and
    a stored hash — defense in depth on top of the exact-match DB lookup
    used to find the row in the first place."""
    return hmac.compare_digest(hash_token(raw_token), stored_hash)
