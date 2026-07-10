"""Email verification link building and TTL.

Mirrors app/password_reset.py exactly, sharing the same token primitives
from app/tokens.py. The only real differences between the two features are
here: verification tokens live longer than reset tokens (24 hours vs 30
minutes) since verifying is lower-stakes than resetting a password and
people often don't check email right after signing up, and the link points
at a different frontend route.
"""

from app.tokens import FRONTEND_BASE_URL, generate_token, hash_token, tokens_match

generate_verification_token = generate_token
hash_verification_token = hash_token

VERIFICATION_TOKEN_TTL_HOURS = 24


def build_verification_link(raw_token: str) -> str:
    return f"{FRONTEND_BASE_URL}/verify-email?token={raw_token}"
