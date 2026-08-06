"""Phase 25 -- Google Sign-In: configuration, server-side ID token
verification, and account find-or-link/create logic.

Everything here runs SERVER-SIDE only -- the frontend never sees, parses,
or is trusted for any claim out of a Google token. The verification chain
(verify_google_id_token) checks issuer, audience, expiration (all via
PyJWT's own `jwt.decode` against Google's published JWKS -- no custom
crypto), plus `nonce` and `email_verified`, which PyJWT has no built-in
opinion on and this module checks explicitly. A token that fails ANY of
these checks is rejected outright; there is no partial trust.

No new AI/HTTP-client abstraction was introduced: `requests` (already a
dependency, used by app.email.resend_provider and the AI providers) is
reused for the one outbound call this module makes (exchanging an
authorization `code` for tokens at Google's token endpoint). ID token
signature verification uses PyJWT's built-in `PyJWKClient`, which is
already available (this app already depends on `pyjwt[crypto]`-compatible
`cryptography` for other RS256 needs) -- no new third-party OAuth library.
"""

import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote as url_quote

import jwt
import requests
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.membership_role import MembershipRole
from app.models import GoogleOAuthHandoff, GoogleOAuthState, Organization, OrganizationMember, User
from app.security import hash_password

logger = logging.getLogger(__name__)

# --- configuration -----------------------------------------------------

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
# Explicit opt-in flag, independent of whether the three values above are
# actually set -- lets an operator disable Google Sign-In outright (e.g.
# to roll it back) without unsetting credentials, mirroring
# app.services.platform_settings.ai_enabled's own "configured vs enabled"
# distinction for the AI assistant.
GOOGLE_OAUTH_ENABLED = os.environ.get("GOOGLE_OAUTH_ENABLED", "false").strip().lower() == "true"

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# Google's ID tokens are issued under either form across different API
# versions/docs -- both are accepted, neither alone.
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

STATE_TTL_MINUTES = 10
HANDOFF_TTL_MINUTES = 2
_TOKEN_REQUEST_TIMEOUT_SECONDS = 10

_jwks_client: PyJWKClient | None = None


def is_google_oauth_configured() -> bool:
    """Cheap check with no network call -- mirrors app.ai.factory
    .is_ai_configured()'s role: lets a caller (the frontend's own login/
    register pages, via GET /auth/google/config) decide whether to show
    the "Continue with Google" button at all, without needing to attempt
    the flow and fail."""
    return bool(GOOGLE_OAUTH_ENABLED and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


class GoogleOAuthError(Exception):
    """Raised for any Google Sign-In failure the caller should show a
    clean, generic error for -- invalid/expired state, token exchange
    failure, ID token verification failure, or Google being unreachable.
    Deliberately a single exception type: the router never needs to
    distinguish these for the end user (all become the same generic
    "Google sign-in failed" message), only logs the specific reason
    server-side."""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# --- state / nonce (CSRF + replay protection for the redirect) -------------


@dataclass(frozen=True)
class GoogleAuthorizationRequest:
    authorization_url: str
    state: str


def begin_authorization(db: Session) -> GoogleAuthorizationRequest:
    """Creates a fresh, single-use (state, nonce) pair and returns the
    full Google authorization URL to redirect the browser to. `state` is
    ALSO set as a short-lived httpOnly cookie by the router (double-
    submit binding -- see app.routers.auth.google_start) so the callback
    can verify the SAME BROWSER that started this flow is the one
    completing it, not just that some valid state value exists (a bare
    "is this state known to the server" check alone doesn't stop a login-
    CSRF: an attacker could complete their own flow and hand a victim a
    valid callback URL logging them into the attacker's account)."""
    now = datetime.now(timezone.utc)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    db.add(
        GoogleOAuthState(
            state=state,
            nonce=nonce,
            expires_at=now + timedelta(minutes=STATE_TTL_MINUTES),
        )
    )
    db.commit()

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        # Always shows the account chooser rather than silently reusing
        # whatever Google session happens to be active in the browser --
        # the safer default for a shared/kiosk browser, and it avoids a
        # surprising silent sign-in as the "wrong" Google account.
        "prompt": "select_account",
    }
    query = "&".join(f"{k}={url_quote(v, safe='')}" for k, v in params.items())
    return GoogleAuthorizationRequest(
        authorization_url=f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}", state=state
    )


def _consume_state(db: Session, *, state: str, cookie_state: str | None) -> GoogleOAuthState:
    """Validates and consumes a state value -- unknown, expired, already-
    used, and cookie-mismatched are all treated identically (a single
    GoogleOAuthError), never distinguished to the caller, matching this
    app's existing "don't let an error message become an oracle"
    discipline (see e.g. app.routers.auth.reset_password's own identical
    treatment of unknown/expired/used tokens)."""
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise GoogleOAuthError("state/cookie mismatch")

    now = datetime.now(timezone.utc)
    record = db.scalar(
        select(GoogleOAuthState).where(
            GoogleOAuthState.state == state,
            GoogleOAuthState.used_at.is_(None),
            GoogleOAuthState.expires_at > now,
        )
    )
    if record is None:
        raise GoogleOAuthError("unknown, expired, or already-used state")

    record.used_at = now
    db.commit()
    return record


# --- ID token verification ---------------------------------------------


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(GOOGLE_JWKS_URL)
    return _jwks_client


@dataclass(frozen=True)
class GoogleIdentity:
    """Only the claims this app actually uses -- never the raw decoded
    token dict, so a caller can't accidentally read (or a future change
    can't accidentally start relying on) a claim this module hasn't
    explicitly validated the meaning of."""

    sub: str
    email: str
    email_verified: bool
    name: str | None
    # Google's own "locale" claim (e.g. "en", "es-419") when present --
    # used only to seed a brand-new Google-only account's own
    # User.language notification preference (see create_google_user);
    # never trusted for anything security-relevant.
    locale: str | None


def _exchange_code_for_id_token(code: str) -> str:
    try:
        response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=_TOKEN_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise GoogleOAuthError(f"token endpoint unreachable: {exc}") from exc

    if not response.ok:
        raise GoogleOAuthError(f"token exchange failed: {response.status_code}")

    body = response.json()
    id_token = body.get("id_token")
    if not id_token:
        raise GoogleOAuthError("token response had no id_token")
    return id_token


def verify_google_id_token(id_token: str, *, expected_nonce: str) -> GoogleIdentity:
    """The one place a Google ID token is ever decoded and trusted.
    Validates, via PyJWT against Google's own published signing keys:
    signature, issuer, audience, and expiration (all built into
    `jwt.decode`'s own argument set) -- plus `nonce` (replay protection:
    must match the value THIS flow generated) and `email_verified` (an
    unverified email must never be used to link or create an account --
    see find_or_link_user's own docstring for exactly why) checked
    explicitly, since PyJWT has no built-in opinion on either. ANY
    failure raises GoogleOAuthError; there is no degraded/partial accept
    path."""
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=GOOGLE_CLIENT_ID,
            issuer=list(GOOGLE_ISSUERS),
        )
    except jwt.PyJWTError as exc:
        raise GoogleOAuthError(f"ID token verification failed: {exc}") from exc
    except requests.RequestException as exc:
        raise GoogleOAuthError(f"JWKS endpoint unreachable: {exc}") from exc

    if claims.get("nonce") != expected_nonce:
        raise GoogleOAuthError("nonce mismatch (possible replay)")
    if claims.get("email_verified") is not True:
        raise GoogleOAuthError("Google account email is not verified")

    email = claims.get("email")
    sub = claims.get("sub")
    if not email or not sub:
        raise GoogleOAuthError("ID token missing required claims")

    return GoogleIdentity(
        sub=sub,
        email=email.strip().lower(),
        email_verified=True,
        name=claims.get("name"),
        locale=claims.get("locale"),
    )


# --- account find-or-link / create --------------------------------------


def find_or_link_user(db: Session, identity: GoogleIdentity) -> User:
    """Resolves a verified Google identity to a User -- never creates a
    duplicate account for the same person.

    Lookup is by `google_sub` FIRST (the stable identifier for "we've
    seen this exact Google account before"), never by email alone: an
    email address is not a permanently stable identifier (Google
    accounts can change their primary address), so keying on it directly
    would risk two different signals disagreeing over time. Only when no
    user is already linked to this `sub` do we fall back to an
    email-based lookup, to LINK (never silently merge data into) an
    existing password-based account -- and only because
    identity.email_verified is already guaranteed true by
    verify_google_id_token (an unverified email could belong to anyone,
    so linking on it would be a account-takeover vector: an attacker
    registering an unverified Google account using a victim's real email
    address could otherwise hijack the victim's existing account).

    Returns the existing User with google_sub now set (linking), or the
    same User unchanged if it was already linked. Callers needing a
    brand-new account (no existing user at all) call
    create_google_user instead."""
    existing_by_sub = db.scalar(select(User).where(User.google_sub == identity.sub))
    if existing_by_sub is not None:
        return existing_by_sub

    existing_by_email = db.scalar(select(User).where(User.email == identity.email))
    if existing_by_email is not None:
        existing_by_email.google_sub = identity.sub
        db.commit()
        db.refresh(existing_by_email)
        return existing_by_email

    return create_google_user(db, identity)


def create_google_user(db: Session, identity: GoogleIdentity) -> User:
    """Creates a brand-new User (Google-only -- password_set=False) plus
    exactly one Organization it owns, mirroring
    app.routers.auth.register()'s own invariants (new org, owner
    membership, real subscription on the platform's current default
    plan) so a Google sign-up account is indistinguishable in every
    other respect from a password sign-up account. `hashed_password` is
    still populated (the column stays NOT NULL) with a bcrypt hash of a
    random, never-revealed value -- see User.password_set's own
    docstring for why this is safe and requires no special-cased login
    branch. Email is marked verified immediately: Google already proved
    it (identity.email_verified is guaranteed true by the caller), so
    there is nothing our own verification email would add.
    """
    # Imported locally to avoid a module-level circular import
    # (app.routers.auth -> app.google_oauth -> app.services.entitlements
    # -> ... -> app.routers.auth is not actually circular today, but
    # keeping billing/entitlements imports local here matches this
    # module's narrow, auth-focused top-level import set).
    from app.billing.service import BillingService
    from app.localization import SUPPORTED_LANGUAGES
    from app.services.entitlements import get_default_plan
    from app.services.platform_settings import get_effective_settings

    settings = get_effective_settings(db)

    # Google's locale claim is a loose BCP-47 tag ("en", "es-419", "en-GB",
    # ...) -- only its language subtag is ever consulted, and only when it
    # matches a language this app actually supports; anything else (or no
    # claim at all) leaves User.language NULL, falling through to the
    # organization's own language exactly like any other account.
    locale_language = (identity.locale or "").split("-")[0].lower()
    user_language = locale_language if locale_language in SUPPORTED_LANGUAGES else None

    user = User(
        email=identity.email,
        hashed_password=hash_password(secrets.token_urlsafe(48)),
        password_set=False,
        google_sub=identity.sub,
        email_verified_at=datetime.now(timezone.utc),
        language=user_language,
    )
    db.add(user)
    db.flush()

    organization_name = f"{identity.name}'s Organization" if identity.name else f"{identity.email.split('@')[0]}'s Organization"
    default_plan = get_default_plan(db)
    organization = Organization(
        name=organization_name,
        language=settings.default_language,
        currency_code=settings.default_currency,
        plan_id=default_plan.id,
    )
    db.add(organization)
    db.flush()

    membership = OrganizationMember(
        user_id=user.id, organization_id=organization.id, role=MembershipRole.owner.value
    )
    db.add(membership)
    db.flush()

    BillingService(db).create_subscription(organization.id, default_plan.id, actor=user)
    db.refresh(user)
    return user


# --- handoff (redirect result -> frontend exchange) -------------------


def create_handoff(db: Session, user_id: str) -> str:
    code = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(
        GoogleOAuthHandoff(
            code=code, user_id=user_id, expires_at=now + timedelta(minutes=HANDOFF_TTL_MINUTES)
        )
    )
    db.commit()
    return code


def consume_handoff(db: Session, code: str) -> User | None:
    """Single-use: a second attempt with the same code (a replay, or a
    user hitting back/refresh on the callback page) returns None, same
    as an unknown or expired code -- never distinguished to the caller."""
    now = datetime.now(timezone.utc)
    record = db.scalar(
        select(GoogleOAuthHandoff).where(
            GoogleOAuthHandoff.code == code,
            GoogleOAuthHandoff.used_at.is_(None),
            GoogleOAuthHandoff.expires_at > now,
        )
    )
    if record is None:
        return None
    record.used_at = now
    db.commit()
    return db.get(User, record.user_id)


def complete_google_sign_in(db: Session, *, code: str, state: str, cookie_state: str | None) -> User:
    """The full server-side callback flow: consume state -> exchange code
    -> verify ID token -> find-or-link/create user. Raises
    GoogleOAuthError on any failure; the router maps that to a redirect
    carrying a generic error, never a raw exception message (which could
    leak provider internals)."""
    state_record = _consume_state(db, state=state, cookie_state=cookie_state)
    id_token = _exchange_code_for_id_token(code)
    identity = verify_google_id_token(id_token, expected_nonce=state_record.nonce)
    return find_or_link_user(db, identity)
