# Google Sign-In (Phase 25)

## Status

Disabled by default. Even with `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/
`GOOGLE_REDIRECT_URI` all set, `GOOGLE_OAUTH_ENABLED` must also be `true`
(a separate, explicit opt-in — see `app.google_oauth.is_google_oauth_configured`)
before "Continue with Google" appears on the login/register page at all,
or before any of the five new endpoints do anything but 503. Password
login/registration are completely unchanged and remain fully functional
whether or not Google Sign-In is enabled.

## Architecture

Server-side authorization-code OAuth 2.0 / OpenID Connect flow — never
the frontend trusting a client-side token. No new third-party OAuth
library or AI-provider-style abstraction: `requests` (already a
dependency) does the one outbound call (exchanging a code for tokens),
and PyJWT's built-in `PyJWKClient` verifies the returned ID token's
signature against Google's own published keys (this app already depends
on `cryptography` for other RS256 needs).

```
app/google_oauth.py   config, begin_authorization/consume_state (CSRF +
                       replay protection), verify_google_id_token (the
                       ONE place a token is ever trusted), find_or_link_user
                       / create_google_user (account resolution),
                       create_handoff/consume_handoff (redirect -> frontend
                       handoff).
app/routers/auth.py   5 new endpoints (see API below), added to the
                       existing /auth router -- no new router file, since
                       this is one more way to reach the exact same
                       AuthResponse login/register already produce.
app/models.py          GoogleOAuthState, GoogleOAuthHandoff (both mirror
                       PasswordResetToken/EmailVerificationToken's own
                       "opaque, single-use, time-boxed" shape exactly);
                       User.google_sub / .password_set / .language.
```

## OAuth flow

```
Browser                Backend                          Google
  |-- GET /auth/google/start ------->|
  |                                   |-- creates (state, nonce) row
  |                                   |-- sets httpOnly state cookie
  |<-- 302 to accounts.google.com ---|
  |----------------------------------------------------->|
  |                                   (user signs in / consents)
  |<---------------------------------- 302 back with ?code&state --------|
  |-- GET /auth/google/callback ----->|
  |    (code, state, cookie)          |-- validates state == cookie (CSRF)
  |                                   |-- consumes state row (replay-proof)
  |                                   |-- exchanges code for id_token ------>|
  |                                   |<----------------------------------- |
  |                                   |-- verifies id_token (JWKS, iss, aud,
  |                                   |     exp, nonce, email_verified)
  |                                   |-- find-or-link-or-create User
  |                                   |-- creates one-time handoff code
  |<-- 302 to FRONTEND/login?google_handoff=... --------|
  |-- POST /auth/google/exchange ---->|
  |    { code: handoff }              |-- consumes handoff, mints a real JWT
  |<-- AuthResponse (same shape as login/register) ------|
```

The real access token is **never** placed in a URL, redirect, or browser
history at any point — only the short-lived, single-use, opaque handoff
code is (2-minute TTL). The ID token itself never leaves the backend.

## Security

Every item from this phase's own required test list is enforced and has
a corresponding test in `tests/test_google_auth.py`:

- **Issuer** — `jwt.decode(..., issuer=["https://accounts.google.com", "accounts.google.com"])`.
- **Audience** — `jwt.decode(..., audience=GOOGLE_CLIENT_ID)`.
- **Expiration** — built into `jwt.decode` (rejects an expired token).
- **Signature** — verified against Google's live JWKS via `PyJWKClient`; a
  token signed by any other key is rejected.
- **Nonce (replay)** — the ID token's `nonce` claim must match the value
  generated at `/start` and stored server-side; a captured/replayed ID
  token from a different flow fails this check.
- **`email_verified`** — must be `true`, checked explicitly (PyJWT has no
  opinion on this claim). An unverified email is never used to link or
  create an account — see [Account linking](#account-linking-rules).
- **State (CSRF)** — double-submit: the `state` query param Google echoes
  back must match the httpOnly `google_oauth_state` cookie set at
  `/start`, AND match an unused, unexpired `GoogleOAuthState` row. Either
  mismatch fails the whole callback with a generic error.
- **Replay of `state`/handoff** — both are marked `used_at` the instant
  they're consumed; a second attempt with the same value fails identically
  to an unknown/expired one (no oracle).
- **Redirect validation** — `redirect_uri` is a fixed, pre-registered,
  non-user-suppliable value (Google itself enforces exact-match
  registration); the frontend landing page after the handoff is always
  the fixed `/login` route, never a caller-supplied URL (no open redirect
  surface).
- **Disabled account** — checked at both the callback (redirects to a
  clean error) and the exchange endpoint (403), exactly like password
  login's own disabled-account check.
- **Provider unavailable** — a network failure talking to Google's token
  or JWKS endpoint raises `GoogleOAuthError`, mapped to the same generic
  `google_failed` redirect as any other verification failure — never a
  raw exception or stack trace.
- **No account takeover** — see [Account linking](#account-linking-rules).

## Account linking rules

`app.google_oauth.find_or_link_user`:

1. **Existing `google_sub` match** → sign in as that user. (The stable
   identifier for "we've seen this exact Google account before" — never
   email alone, since an email is not permanently stable.)
2. **No `sub` match, but an existing user has this email** (and Google's
   `email_verified` claim is `true`, always guaranteed by this point) →
   **link** `google_sub` onto that existing account. The account's
   password (if any) keeps working exactly as before — Google becomes an
   *additional* way in, never a replacement.
3. **No match at all** → create a brand-new account (a new `User` +
   exactly one `Organization` it owns, mirroring `/auth/register`'s own
   invariants) with `password_set=false` and `email_verified_at` set
   immediately (Google already proved the email; there is nothing our own
   verification email would add).

Never creates a duplicate `User` row for the same person. Linking is only
ever done on a Google-**verified** email — an unverified email is
rejected outright by `verify_google_id_token`, closing the obvious
account-takeover vector (an attacker registering an unverified Google
account with a victim's real email address).

## Password-less accounts

A Google-only account still has a `hashed_password` value (the column
stays `NOT NULL` — no schema migration needed to make it nullable): a
bcrypt hash of a random, 48-byte value that's never revealed anywhere.
Ordinary password login simply always fails for it, exactly like a wrong
password — no special-cased login branch, no new information-disclosure
oracle. `User.password_set=false` is the actual signal
`/auth/google/disconnect` checks.

A Google-only user can set a real password at any time using the
existing **Forgot password** flow (`/forgot-password` → `/reset-password`)
— it works by email alone and doesn't require an existing password;
`reset_password` sets `password_set=true` the moment a password is
chosen, after which "Disconnect Google" becomes available in Settings.

## API

| Endpoint | Behavior |
| --- | --- |
| `GET /auth/google/config` | `{enabled: bool}` — no network call; the login page uses this to decide whether to render the button. |
| `GET /auth/google/start` | 302 to Google; sets the httpOnly `google_oauth_state` cookie (10-minute TTL, path `/auth/google`). |
| `GET /auth/google/callback` | Google's own redirect target. 302 back to `{FRONTEND_BASE_URL}/login` with either `?google_handoff=<code>` or `?google_error=<code>`. |
| `POST /auth/google/exchange` | Body `{code}`. Returns the same `AuthResponse` shape as `/auth/login`/`/auth/register`. |
| `POST /auth/google/disconnect` | Authenticated. 400 if not linked; **409** if Google is the account's only login method (`password_set=false`); otherwise unlinks. |

All five are rate-limited (`app.rate_limit.GOOGLE_START_RULES` /
`GOOGLE_CALLBACK_RULES` / `GOOGLE_EXCHANGE_RULES`), matching the existing
login/register rate-limit posture.

## Session storage audit & migration strategy

**Current state (unchanged by this phase):** the main application session
is a Bearer JWT (`app.security.create_access_token`, HS256, 24h default
expiry) stored in `localStorage` under 10 separate keys
(`frontend/lib/auth-storage.ts`). There is no server-side session table,
no refresh-token rotation — a single long-lived token, sent as
`Authorization: Bearer <token>` on every request. Logout
(`clearAuthSession()`) simply removes the local keys; the token itself
remains cryptographically valid until it naturally expires (there is no
server-side revocation list). This is unchanged by Google Sign-In: the
JWT this flow ultimately mints (at `/auth/google/exchange`) is the exact
same kind of token `/auth/login`/`/auth/register` already issue, stored
the same way.

**Why the main session was NOT moved to cookies in this phase:** the spec
for this phase explicitly qualifies the ask with "if practical without
breaking architecture" and "do not break current deployments." A
Bearer-token-in-localStorage design is threaded through this codebase at
every layer — every `apiFetch` call site, the WhatsApp bridge's own
backend-to-backend auth, Organization API Keys (a parallel, unrelated
auth mechanism), and every existing test's `auth_headers` fixture. Moving
the primary session to an httpOnly cookie would require, at minimum: a
CSRF token scheme (cookies are sent automatically by the browser on
every request, unlike a Bearer header, which is the classic CSRF
exposure a cookie-based session reintroduces), a `SameSite`/cross-origin
strategy compatible with the frontend and backend being deployed on
different origins/subdomains (`localhost:3000` vs `127.0.0.1:8000` in
dev; separate Render/Vercel domains in production), and a coordinated
frontend rewrite of every authenticated `fetch` call. That is a
substantial, high-blast-radius rewrite, not a "if practical" change — so
it was deliberately not done here. **This is a genuine, tracked
limitation, not an oversight** — see
[Remaining production recommendations](#remaining-production-recommendations-excerpt)
below for the concrete follow-up phase this implies.

**What this phase DOES add, and why it's safe:** exactly one new cookie —
`google_oauth_state` — used only during the few seconds of the OAuth
redirect round-trip, for CSRF-binding that specific flow (see
[Security](#security) above). It is httpOnly, `Secure` in production,
`SameSite=Lax`, scoped to path `/auth/google`, and expires after 10
minutes (explicitly deleted at the end of both the success and failure
paths). It carries no user identity or session data — only an opaque
`state` value. See `docs/cookies.md` for the full inventory and why this
one cookie does not require a consent banner.

**No token leakage audit:** grepped for any place a raw JWT or ID token
could reach a log line — none found. Every `logger.*` call in the auth
path logs only booleans, ids, or error codes (see e.g.
`app.google_oauth`'s own logging, which never logs `id_token` or the
minted access token). The ID token is verified and discarded within
`verify_google_id_token`; nothing beyond `sub`/`email`/`email_verified`/
`name`/`locale` ever leaves that function.

## Configuration

See `.env.example` (`GOOGLE_OAUTH_ENABLED`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, and the pre-existing
`FRONTEND_BASE_URL`, reused as the callback's landing target). Register
an OAuth 2.0 Client ID (type: Web application) in the Google Cloud
Console, add `{your backend URL}/auth/google/callback` as an authorized
redirect URI, and copy the generated client ID/secret.

## Limitations

- A custom "Advanced: API base URL" value on the login page (a local-dev/
  self-host convenience) is **not** preserved across the Google redirect
  round-trip — the handoff exchange always uses the frontend's default
  configured API URL (`NEXT_PUBLIC_API_URL`). Self-hosters pointing the
  frontend at a non-default backend should set that build-time variable
  rather than relying on the runtime override for this one flow.
- Google's `locale` claim (used only to seed a brand-new account's
  notification-language preference — see `docs/localization.md`) is
  informal and not always present; when absent or unsupported, the new
  account falls through to the organization's language exactly like any
  other account.
- No account-merge UI exists for the rare case where a user wants to
  manually merge two genuinely separate accounts they created with
  different emails — out of scope for this phase.

## Remaining production recommendations (excerpt)

See the Final Report's own "Remaining production recommendations"
section for the complete list; the session-storage-specific one:
**migrate the primary session to httpOnly cookies with CSRF protection**
as its own, dedicated follow-up phase — sized and scoped independently,
touching every API call site deliberately rather than as a side effect of
this one.
