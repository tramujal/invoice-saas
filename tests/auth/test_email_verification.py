"""Email-verification token lifecycle -- same rationale as
test_password_reset.py for calling issue_email_verification() directly
rather than going through /auth/register or /auth/resend-verification's
background task.
"""

from datetime import datetime, timedelta, timezone

from app.email_verification import hash_verification_token
from app.models import EmailVerificationToken
from app.routers.auth import issue_email_verification
from tests.factories import make_user


def test_verify_email_succeeds_with_valid_token(client, db_session):
    user = make_user(db_session, email="verify@example.com", verified=False)
    raw_token = issue_email_verification(db_session, user)

    response = client.post("/auth/verify-email", json={"token": raw_token})
    assert response.status_code == 200

    db_session.refresh(user)
    assert user.email_verified_at is not None


def test_verify_email_token_is_single_use(client, db_session):
    user = make_user(db_session, email="verify2@example.com", verified=False)
    raw_token = issue_email_verification(db_session, user)

    first = client.post("/auth/verify-email", json={"token": raw_token})
    assert first.status_code == 200

    second = client.post("/auth/verify-email", json={"token": raw_token})
    assert second.status_code == 400


def test_verify_email_rejects_expired_token(client, db_session):
    user = make_user(db_session, email="verify3@example.com", verified=False)
    raw_token = issue_email_verification(db_session, user)

    token_row = db_session.query(EmailVerificationToken).filter_by(user_id=user.id).one()
    token_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    response = client.post("/auth/verify-email", json={"token": raw_token})
    assert response.status_code == 400


def test_verification_token_stored_hashed_not_raw(db_session):
    user = make_user(db_session, email="verify4@example.com", verified=False)
    raw_token = issue_email_verification(db_session, user)

    token_row = db_session.query(EmailVerificationToken).filter_by(user_id=user.id).one()
    assert token_row.token_hash != raw_token
    assert token_row.token_hash == hash_verification_token(raw_token)


def test_resend_verification_no_ops_when_already_verified(client, db_session):
    user = make_user(db_session, email="verify5@example.com", verified=True)
    from tests.factories import make_organization, make_membership
    from app.membership_role import MembershipRole
    from app.security import create_access_token

    organization = make_organization(db_session)
    make_membership(db_session, user, organization, role=MembershipRole.owner)

    response = client.post(
        "/auth/resend-verification",
        headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
    )
    assert response.status_code == 200
    assert "already verified" in response.json()["message"].lower()
