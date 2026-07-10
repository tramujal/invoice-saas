"""Password reset token generation, hashing, and link building.

Reset tokens are high-entropy random strings, not JWTs: a JWT's whole point
is being statelessly verifiable, which is the opposite of what a one-time,
revocable reset link needs (we must be able to mark one used or invalidate
it early, which requires a DB row to flip).

Tokens are hashed with a fast cryptographic hash (SHA-256), not bcrypt.
bcrypt's deliberate slowness exists to resist brute-forcing low-entropy,
human-chosen secrets (passwords). A 256-bit random token from `secrets` is
already computationally infeasible to guess, so a fast hash is both correct
and appropriate here — bcrypt would only add latency with no security
benefit.
"""

import hashlib
import hmac
import os
import secrets

RESET_TOKEN_TTL_MINUTES = 30
_TOKEN_BYTES = 32  # 256 bits of entropy

FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def generate_reset_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def tokens_match(raw_token: str, stored_hash: str) -> bool:
    """Constant-time comparison between a freshly-hashed candidate token and
    a stored hash — defense in depth on top of the exact-match DB lookup
    used to find the row in the first place."""
    return hmac.compare_digest(hash_reset_token(raw_token), stored_hash)


def build_reset_link(raw_token: str) -> str:
    return f"{FRONTEND_BASE_URL}/reset-password?token={raw_token}"
