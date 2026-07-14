"""Password-reset token lifecycle.

Uses issue_password_reset() directly (a service-layer call) rather than
POSTing /auth/forgot-password, since that endpoint issues the token from a
FastAPI BackgroundTask that opens its own SessionLocal() connection --
invisible to this test's isolated db_session transaction until commit,
which never happens within a rolled-back test. reset_password() itself
runs synchronously against the overridden get_db, so it's exercised via
the real HTTP client below.
"""

from datetime import datetime, timedelta, timezone

from app.models import PasswordResetToken
from app.password_reset import hash_reset_token
from app.routers.auth import issue_password_reset
from tests.factories import make_user


def test_reset_password_succeeds_with_valid_token(client, db_session, fake_email_sender):
    user = make_user(db_session, email="reset@example.com")
    raw_token = issue_password_reset(db_session, user)

    response = client.post(
        "/auth/reset-password", json={"token": raw_token, "new_password": "New-Password-1"}
    )
    assert response.status_code == 200

    login = client.post(
        "/auth/login", json={"email": "reset@example.com", "password": "New-Password-1"}
    )
    assert login.status_code == 200


def test_reset_password_token_is_single_use(client, db_session):
    user = make_user(db_session, email="reset2@example.com")
    raw_token = issue_password_reset(db_session, user)

    first = client.post(
        "/auth/reset-password", json={"token": raw_token, "new_password": "New-Password-1"}
    )
    assert first.status_code == 200

    second = client.post(
        "/auth/reset-password", json={"token": raw_token, "new_password": "Another-Password-2"}
    )
    assert second.status_code == 400


def test_reset_password_rejects_expired_token(client, db_session):
    user = make_user(db_session, email="reset3@example.com")
    raw_token = issue_password_reset(db_session, user)

    token_row = db_session.query(PasswordResetToken).filter_by(user_id=user.id).one()
    token_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    response = client.post(
        "/auth/reset-password", json={"token": raw_token, "new_password": "New-Password-1"}
    )
    assert response.status_code == 400


def test_reset_password_rejects_unknown_token(client):
    response = client.post(
        "/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "New-Password-1"},
    )
    assert response.status_code == 400


def test_reset_token_stored_hashed_not_raw(db_session):
    user = make_user(db_session, email="reset4@example.com")
    raw_token = issue_password_reset(db_session, user)

    token_row = db_session.query(PasswordResetToken).filter_by(user_id=user.id).one()
    assert token_row.token_hash != raw_token
    assert token_row.token_hash == hash_reset_token(raw_token)


def test_issuing_new_reset_token_invalidates_prior_one(client, db_session):
    user = make_user(db_session, email="reset5@example.com")
    old_token = issue_password_reset(db_session, user)
    new_token = issue_password_reset(db_session, user)
    assert old_token != new_token

    old_attempt = client.post(
        "/auth/reset-password", json={"token": old_token, "new_password": "New-Password-1"}
    )
    assert old_attempt.status_code == 400

    new_attempt = client.post(
        "/auth/reset-password", json={"token": new_token, "new_password": "New-Password-1"}
    )
    assert new_attempt.status_code == 200
