"""Rate limits trip at their configured threshold with a 429 + the
machine-readable rate_limit_exceeded code, using the per-test backend
reset (see conftest.py's autouse _reset_rate_limiter) -- no real sleeping,
no timing flakiness. Each bucket is independent per test, so hitting a
limit here can never bleed into another test's requests."""

from app.rate_limit import RATE_LIMIT_CODE
from tests.factories import make_org_with_owner, make_user


def test_register_rate_limit_trips_after_configured_count(client):
    # REGISTER_RULES = 3/hour, keyed by IP -- TestClient uses a fixed
    # synthetic client IP, so all requests in this test share one bucket.
    for i in range(3):
        response = client.post(
            "/auth/register",
            json={
                "email": f"reguser{i}@example.com",
                "password": "Correct-Horse-1",
                "organization_name": "Acme Inc",
            },
        )
        assert response.status_code == 201

    fourth = client.post(
        "/auth/register",
        json={
            "email": "reguser4@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "Acme Inc",
        },
    )
    assert fourth.status_code == 429
    assert fourth.json()["detail"]["code"] == RATE_LIMIT_CODE
    assert "Retry-After" in fourth.headers


def test_login_ip_rate_limit_trips_after_configured_count(client, db_session):
    # LOGIN_IP_RULES's tightest rule is 5/min -- deliberately using the
    # wrong password so failed attempts still count toward the IP bucket
    # (enforce_rate_limit runs before credential verification).
    make_user(db_session, email="loginlimit@example.com")

    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"email": "loginlimit@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401

    sixth = client.post(
        "/auth/login",
        json={"email": "loginlimit@example.com", "password": "wrong-password"},
    )
    assert sixth.status_code == 429
    assert sixth.json()["detail"]["code"] == RATE_LIMIT_CODE


def test_assistant_chat_rate_limit_trips_after_configured_count(client, db_session):
    # ASSISTANT_CHAT_RULES = 20/hour, keyed by user (and user+ip) -- uses
    # the autouse fake_ai_provider, never a real model call.
    owner = make_org_with_owner(db_session, email="assistant-owner@example.com")
    org_id = owner.organization.id

    for _ in range(20):
        response = client.post(
            f"/organizations/{org_id}/assistant/chat",
            json={"message": "hello"},
            headers=owner.auth_headers,
        )
        assert response.status_code == 200

    blocked = client.post(
        f"/organizations/{org_id}/assistant/chat",
        json={"message": "hello"},
        headers=owner.auth_headers,
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == RATE_LIMIT_CODE


def test_rate_limit_buckets_are_independent_per_user(client, db_session):
    """A blocked user's assistant-chat bucket must never affect a
    different user's own bucket -- both ASSISTANT_CHAT_RULES buckets
    (user-only and user+ip) include the user_id in their key, so even two
    users sharing TestClient's one synthetic IP stay fully independent.
    Otherwise one org's heavy usage could deny service to every other
    tenant on the same rate limiter process."""
    org_a = make_org_with_owner(db_session, email="tenant-a@example.com", org_name="Tenant A")
    org_b = make_org_with_owner(db_session, email="tenant-b@example.com", org_name="Tenant B")

    for _ in range(20):
        client.post(
            f"/organizations/{org_a.organization.id}/assistant/chat",
            json={"message": "hello"},
            headers=org_a.auth_headers,
        )
    blocked = client.post(
        f"/organizations/{org_a.organization.id}/assistant/chat",
        json={"message": "hello"},
        headers=org_a.auth_headers,
    )
    assert blocked.status_code == 429

    still_allowed = client.post(
        f"/organizations/{org_b.organization.id}/assistant/chat",
        json={"message": "hello"},
        headers=org_b.auth_headers,
    )
    assert still_allowed.status_code == 200
