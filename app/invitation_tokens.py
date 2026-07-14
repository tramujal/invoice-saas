"""Organization invitation link building and TTL.

Mirrors app/password_reset.py exactly, sharing the same token primitives
from app/tokens.py: hashed at rest, single-use, high-entropy. Unlike the
Quotes feature's public link (deliberately stored raw, since that's a
durable, reusable share link), an invitation is genuinely a one-time,
short-lived credential -- the same shape password reset and email
verification already are -- so the hash-at-rest pattern applies directly
here, per the user's explicit instruction to reuse it.

7 days is longer than password reset (30 minutes) or email verification
(24 hours): a real person has to see the email, and -- if they don't have
an account yet -- register before they can accept, so this needs more
slack than either of those lower-stakes, faster flows.
"""

from app.tokens import FRONTEND_BASE_URL, generate_token, hash_token, tokens_match

generate_invitation_token = generate_token
hash_invitation_token = hash_token
invitation_tokens_match = tokens_match

INVITATION_TOKEN_TTL_HOURS = 24 * 7


def build_invitation_link(raw_token: str) -> str:
    return f"{FRONTEND_BASE_URL}/accept-invitation?token={raw_token}"
