"""Password reset link building and TTL.

Token generation/hashing/comparison and FRONTEND_BASE_URL live in
app/tokens.py, shared with app/email_verification.py — this module only adds
what's actually specific to password reset: how long a token lives and what
link it builds. Re-exports generate_token/hash_token/tokens_match under
their original names so existing importers (app/routers/auth.py) don't need
to change.
"""

from app.tokens import FRONTEND_BASE_URL, generate_token, hash_token, tokens_match

generate_reset_token = generate_token
hash_reset_token = hash_token

RESET_TOKEN_TTL_MINUTES = 30


def build_reset_link(raw_token: str) -> str:
    return f"{FRONTEND_BASE_URL}/reset-password?token={raw_token}"
