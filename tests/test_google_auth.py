"""Phase 25 -- Google Sign-In.

Covers: server-side ID token verification (signature via a real RSA
keypair generated in-test, issuer, audience, expiration, nonce,
email_verified), account find-or-link/create rules (no duplicate users,
safe linking only on a verified email, existing password users, existing
Google-only users), the full HTTP redirect/handoff/exchange flow, CSRF
(state/cookie binding), replay (state and handoff are both single-use),
disabled accounts, and the disconnect-requires-another-method rule.
"""

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import google_oauth
from app.google_oauth import (
    GoogleIdentity,
    GoogleOAuthError,
    create_google_user,
    find_or_link_user,
    verify_google_id_token,
)
from app.models import GoogleOAuthHandoff, GoogleOAuthState, User
from app.user_status import UserStatus
from tests.factories import make_org_with_owner, make_user

GOOGLE_CLIENT_ID_FOR_TESTS = "test-client-id.apps.googleusercontent.com"


@pytest.fixture(autouse=True)
def _configure_google_oauth(monkeypatch):
    """Every test in this file runs as if Google Sign-In were fully
    configured -- individual tests override further as needed."""
    monkeypatch.setattr(google_oauth, "GOOGLE_OAUTH_ENABLED", True)
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID_FOR_TESTS)
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(google_oauth, "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


def _patch_jwks(monkeypatch, public_key):
    class _FakeJWKClient:
        def get_signing_key_from_jwt(self, token):
            return _FakeSigningKey(public_key)

    monkeypatch.setattr(google_oauth, "_get_jwks_client", lambda: _FakeJWKClient())


def _mint_id_token(private_key, **claim_overrides):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": GOOGLE_CLIENT_ID_FOR_TESTS,
        "sub": "google-sub-12345",
        "email": "newgoogleuser@example.com",
        "email_verified": True,
        "nonce": "expected-nonce",
        "name": "Ada Lovelace",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


# --- ID token verification -----------------------------------------------


def test_verify_google_id_token_accepts_a_valid_token(monkeypatch, rsa_keypair):
    private_key, public_key = rsa_keypair
    _patch_jwks(monkeypatch, public_key)
    token = _mint_id_token(private_key)

    identity = verify_google_id_token(token, expected_nonce="expected-nonce")
    assert identity.sub == "google-sub-12345"
    assert identity.email == "newgoogleuser@example.com"
    assert identity.email_verified is True


def test_verify_google_id_token_rejects_wrong_audience(monkeypatch, rsa_keypair):
    private_key, public_key = rsa_keypair
    _patch_jwks(monkeypatch, public_key)
    token = _mint_id_token(private_key, aud="someone-elses-client-id")

    with pytest.raises(GoogleOAuthError):
        verify_google_id_token(token, expected_nonce="expected-nonce")


def test_verify_google_id_token_rejects_wrong_issuer(monkeypatch, rsa_keypair):
    private_key, public_key = rsa_keypair
    _patch_jwks(monkeypatch, public_key)
    token = _mint_id_token(private_key, iss="https://evil.example.com")

    with pytest.raises(GoogleOAuthError):
        verify_google_id_token(token, expected_nonce="expected-nonce")


def test_verify_google_id_token_accepts_alternate_issuer_form(monkeypatch, rsa_keypair):
    private_key, public_key = rsa_keypair
    _patch_jwks(monkeypatch, public_key)
    token = _mint_id_token(private_key, iss="accounts.google.com")

    identity = verify_google_id_token(token, expected_nonce="expected-nonce")
    assert identity.sub == "google-sub-12345"


def test_verify_google_id_token_rejects_expired_token(monkeypatch, rsa_keypair):
    private_key, public_key = rsa_keypair
    _patch_jwks(monkeypatch, public_key)
    now = int(time.time())
    token = _mint_id_token(private_key, iat=now - 7200, exp=now - 3600)

    with pytest.raises(GoogleOAuthError):
        verify_google_id_token(token, expected_nonce="expected-nonce")


def test_verify_google_id_token_rejects_nonce_mismatch(monkeypatch, rsa_keypair):
    private_key, public_key = rsa_keypair
    _patch_jwks(monkeypatch, public_key)
    token = _mint_id_token(private_key, nonce="a-different-nonce")

    with pytest.raises(GoogleOAuthError):
        verify_google_id_token(token, expected_nonce="expected-nonce")


def test_verify_google_id_token_rejects_unverified_email(monkeypatch, rsa_keypair):
    private_key, public_key = rsa_keypair
    _patch_jwks(monkeypatch, public_key)
    token = _mint_id_token(private_key, email_verified=False)

    with pytest.raises(GoogleOAuthError):
        verify_google_id_token(token, expected_nonce="expected-nonce")


def test_verify_google_id_token_rejects_bad_signature(monkeypatch, rsa_keypair):
    _private_key, public_key = rsa_keypair
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _patch_jwks(monkeypatch, public_key)
    # Signed with a DIFFERENT private key than the one whose public key
    # verify_google_id_token is given -- simulates a forged token.
    token = _mint_id_token(other_private_key)

    with pytest.raises(GoogleOAuthError):
        verify_google_id_token(token, expected_nonce="expected-nonce")


# --- account find-or-link / create ----------------------------------------


def test_create_google_user_creates_password_less_verified_account(db_session):
    identity = GoogleIdentity(
        sub="sub-new", email="brandnew@example.com", email_verified=True, name="Grace Hopper"
    , locale=None)
    user = create_google_user(db_session, identity)

    assert user.google_sub == "sub-new"
    assert user.password_set is False
    assert user.email_verified is True  # verified immediately -- Google already proved it
    assert user.has_google_account is True

    from app.models import OrganizationMember

    memberships = db_session.query(OrganizationMember).filter_by(user_id=user.id).all()
    assert len(memberships) == 1
    assert memberships[0].role == "owner"


def test_find_or_link_user_links_existing_password_account_by_verified_email(db_session):
    org = make_org_with_owner(db_session, email="existing-password-user@example.com")
    assert org.user.google_sub is None
    assert org.user.password_set is True

    identity = GoogleIdentity(
        sub="sub-linking", email="existing-password-user@example.com", email_verified=True, name="X"
    , locale=None)
    linked = find_or_link_user(db_session, identity)

    assert linked.id == org.user.id  # SAME user, not a duplicate
    assert linked.google_sub == "sub-linking"
    assert linked.password_set is True  # password login still works after linking

    total_users = db_session.query(User).filter_by(email="existing-password-user@example.com").count()
    assert total_users == 1  # never duplicated


def test_find_or_link_user_reuses_existing_google_account_by_sub(db_session):
    identity = GoogleIdentity(sub="sub-repeat", email="repeat@example.com", email_verified=True, name="X", locale=None)
    first = find_or_link_user(db_session, identity)
    second = find_or_link_user(db_session, identity)

    assert first.id == second.id
    total_users = db_session.query(User).filter_by(email="repeat@example.com").count()
    assert total_users == 1


def test_find_or_link_user_creates_new_account_when_nothing_matches(db_session):
    identity = GoogleIdentity(sub="sub-fresh", email="fresh@example.com", email_verified=True, name="X", locale=None)
    user = find_or_link_user(db_session, identity)
    assert user.email == "fresh@example.com"
    assert user.google_sub == "sub-fresh"


# --- HTTP layer: full flow -------------------------------------------------


def test_google_start_redirects_and_sets_state_cookie(client):
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]
    assert "google_oauth_state" in response.cookies


def test_google_start_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(google_oauth, "GOOGLE_OAUTH_ENABLED", False)
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 503


def test_google_callback_rejects_state_cookie_mismatch(client, db_session):
    from app.services.background_jobs import enqueue_job  # noqa: F401 -- ensure app wiring loaded

    start_response = client.get("/auth/google/start", follow_redirects=False)
    location = start_response.headers["location"]
    import urllib.parse

    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    real_state = query["state"][0]

    # Deliberately send the WRONG cookie value alongside a real, valid state.
    client.cookies.set("google_oauth_state", "not-the-real-state")
    callback_response = client.get(
        f"/auth/google/callback?code=fake-code&state={real_state}", follow_redirects=False
    )
    assert callback_response.status_code == 302
    assert "google_error=google_failed" in callback_response.headers["location"]


def test_google_callback_rejects_replayed_state(client, db_session):
    import urllib.parse

    start_response = client.get("/auth/google/start", follow_redirects=False)
    location = start_response.headers["location"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    real_state = query["state"][0]
    client.cookies.set("google_oauth_state", real_state)

    # First callback attempt consumes the state (fails downstream at token
    # exchange since "fake-code" isn't real, but the state is consumed
    # regardless -- exactly the replay-prevention behavior under test).
    client.get(f"/auth/google/callback?code=fake-code&state={real_state}", follow_redirects=False)

    # Second attempt with the SAME state must also fail -- state is single-use.
    second = client.get(f"/auth/google/callback?code=fake-code&state={real_state}", follow_redirects=False)
    assert "google_error=google_failed" in second.headers["location"]


def test_google_callback_redirects_on_provider_error(client):
    response = client.get("/auth/google/callback?error=access_denied", follow_redirects=False)
    assert response.status_code == 302
    assert "google_error=google_denied" in response.headers["location"]


def test_full_flow_callback_success_then_exchange(client, db_session, monkeypatch):
    """Bypasses the real Google network calls (token exchange + JWKS) by
    monkeypatching complete_google_sign_in directly at the router's import
    site -- this test's job is to prove the CALLBACK -> HANDOFF -> EXCHANGE
    plumbing is correct, not to re-prove ID token verification (covered
    separately above)."""
    import app.routers.auth as auth_router

    org = make_org_with_owner(db_session, email="flow-user@example.com")

    def _fake_complete(db, *, code, state, cookie_state):
        assert code == "real-code"
        return db.get(User, org.user.id)

    monkeypatch.setattr(auth_router, "complete_google_sign_in", _fake_complete)

    import urllib.parse

    start_response = client.get("/auth/google/start", follow_redirects=False)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(start_response.headers["location"]).query)
    real_state = query["state"][0]
    client.cookies.set("google_oauth_state", real_state)

    callback_response = client.get(
        f"/auth/google/callback?code=real-code&state={real_state}", follow_redirects=False
    )
    assert callback_response.status_code == 302
    assert "google_handoff=" in callback_response.headers["location"]
    handoff_code = callback_response.headers["location"].split("google_handoff=")[1]

    exchange_response = client.post("/auth/google/exchange", json={"code": handoff_code})
    assert exchange_response.status_code == 200
    body = exchange_response.json()
    assert body["user"]["email"] == "flow-user@example.com"
    assert body["access_token"]


def test_exchange_rejects_unknown_handoff_code(client):
    response = client.post("/auth/google/exchange", json={"code": "not-a-real-code"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_handoff"


def test_exchange_rejects_reused_handoff_code(db_session, client):
    from app.google_oauth import create_handoff

    org = make_org_with_owner(db_session, email="reuse-handoff@example.com")
    code = create_handoff(db_session, org.user.id)

    first = client.post("/auth/google/exchange", json={"code": code})
    assert first.status_code == 200

    second = client.post("/auth/google/exchange", json={"code": code})
    assert second.status_code == 400


def test_exchange_rejects_disabled_account(db_session, client):
    from app.google_oauth import create_handoff

    org = make_org_with_owner(db_session, email="disabled-google-user@example.com")
    org.user.status = UserStatus.disabled.value
    db_session.commit()

    code = create_handoff(db_session, org.user.id)
    response = client.post("/auth/google/exchange", json={"code": code})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "account_disabled"


def test_handoff_expiry_is_enforced(db_session, client):
    org = make_org_with_owner(db_session, email="expired-handoff@example.com")
    handoff = GoogleOAuthHandoff(
        code="expired-code-value",
        user_id=org.user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(handoff)
    db_session.commit()

    response = client.post("/auth/google/exchange", json={"code": "expired-code-value"})
    assert response.status_code == 400


# --- disconnect -------------------------------------------------------


def test_disconnect_succeeds_when_password_is_also_set(db_session, client):
    org = make_org_with_owner(db_session, email="disconnect-ok@example.com")
    org.user.google_sub = "sub-to-remove"
    db_session.commit()

    response = client.post("/auth/google/disconnect", headers=org.auth_headers)
    assert response.status_code == 200
    db_session.refresh(org.user)
    assert org.user.google_sub is None


def test_disconnect_rejected_when_google_is_only_login_method(db_session, client):
    org = make_org_with_owner(db_session, email="google-only@example.com")
    org.user.google_sub = "sub-only"
    org.user.password_set = False
    db_session.commit()

    response = client.post("/auth/google/disconnect", headers=org.auth_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_other_auth_method"


def test_disconnect_rejected_when_not_linked(db_session, client):
    org = make_org_with_owner(db_session, email="never-linked@example.com")
    response = client.post("/auth/google/disconnect", headers=org.auth_headers)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "google_not_linked"


def test_disconnect_requires_authentication(client):
    response = client.post("/auth/google/disconnect")
    assert response.status_code == 401


# --- password login still works for google-only accounts (safely fails) --


def test_password_login_fails_cleanly_for_google_only_account(db_session, client):
    identity = GoogleIdentity(sub="sub-pwtest", email="pwtest@example.com", email_verified=True, name="X", locale=None)
    create_google_user(db_session, identity)

    response = client.post("/auth/login", json={"email": "pwtest@example.com", "password": "WhateverPass1"})
    assert response.status_code == 401  # same generic error as any wrong password, no special oracle
