"""Quote public-link token building.

generate_token()/FRONTEND_BASE_URL live in app/tokens.py -- reused here for
the same high-entropy (256-bit) random string generation.

Deliberately NOT hashed at rest, unlike password-reset/email-verification
tokens (app/password_reset.py). Those are one-time, single-use secrets:
generated, emailed, and immediately discarded from memory -- hashing them
protects a credential that's never needed again in plaintext. A quote's
public link is the opposite: a durable, reusable capability URL (the same
link must keep working across "Send", "Resend", and "Copy link", and the
public page itself must be openable indefinitely) -- so the raw token has
to be retrievable at any later point, which a one-way hash cannot support.
This is the same tradeoff countless "shareable link" features make
(payment links, calendar-invite links, etc.): security comes from the
token's entropy and HTTPS transport, not from at-rest hashing. See
Quote.public_token in app/models.py -- stored directly, unique-indexed,
looked up by exact match, never by hash comparison.
"""

from app.tokens import FRONTEND_BASE_URL, generate_token

generate_quote_public_token = generate_token


def build_quote_public_link(raw_token: str) -> str:
    return f"{FRONTEND_BASE_URL}/quotes/public/{raw_token}"
