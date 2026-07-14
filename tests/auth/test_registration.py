from app.membership_role import MembershipRole
from app.models import OrganizationMember, User


def test_register_creates_organization_and_owner_membership(client, db_session):
    response = client.post(
        "/auth/register",
        json={
            "email": "owner@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "Acme Inc",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["access_token"]
    assert body["organizations"][0]["name"] == "Acme Inc"

    user = db_session.query(User).filter_by(email="owner@example.com").one()
    membership = db_session.query(OrganizationMember).filter_by(user_id=user.id).one()
    # Regression coverage: the org-creating user must become owner, not the
    # OrganizationMember.role column default of "member".
    assert membership.role == MembershipRole.owner.value


def test_register_rejects_duplicate_email(client):
    payload = {
        "email": "dup@example.com",
        "password": "Correct-Horse-1",
        "organization_name": "Acme Inc",
    }
    first = client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = client.post("/auth/register", json=payload)
    assert second.status_code == 409


def test_register_rejects_weak_password(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "weak@example.com",
            "password": "alllowercase",
            "organization_name": "Acme Inc",
        },
    )
    assert response.status_code == 422


def test_register_never_stores_plaintext_password(client, db_session):
    client.post(
        "/auth/register",
        json={
            "email": "plain@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "Acme Inc",
        },
    )
    user = db_session.query(User).filter_by(email="plain@example.com").one()
    assert user.hashed_password != "Correct-Horse-1"
    assert "Correct-Horse-1" not in user.hashed_password
