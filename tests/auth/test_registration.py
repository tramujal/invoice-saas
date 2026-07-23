from app.membership_role import MembershipRole
from app.models import Organization, OrganizationMember, User


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


def _super_admin_headers(db_session):
    from app.security import create_access_token
    from tests.factories import make_user

    admin = make_user(db_session, email="settings-admin@example.com")
    admin.platform_role = "super_admin"
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def test_register_blocked_when_registrations_disabled(client, db_session):
    admin_headers = _super_admin_headers(db_session)
    client.patch(
        "/admin/settings",
        json={"reason": "pausing new signups", "expected_version": 1, "registrations_enabled": False},
        headers=admin_headers,
    )

    response = client.post(
        "/auth/register",
        json={
            "email": "blocked-signup@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "Acme Inc",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "registrations_disabled"


def test_register_disabled_does_not_affect_login(client, db_session):
    from tests.factories import make_user

    make_user(db_session, email="already-registered@example.com")
    admin_headers = _super_admin_headers(db_session)
    client.patch(
        "/admin/settings",
        json={"reason": "pausing new signups", "expected_version": 1, "registrations_enabled": False},
        headers=admin_headers,
    )

    response = client.post(
        "/auth/login",
        json={"email": "already-registered@example.com", "password": "Correct-Horse-1"},
    )
    assert response.status_code == 200


def test_register_uses_platform_default_language_and_currency(client, db_session):
    admin_headers = _super_admin_headers(db_session)
    client.patch(
        "/admin/settings",
        json={
            "reason": "expanding to Spain",
            "expected_version": 1,
            "default_language": "es",
            "default_currency": "EUR",
        },
        headers=admin_headers,
    )

    response = client.post(
        "/auth/register",
        json={
            "email": "new-defaults@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "Nueva Empresa",
        },
    )
    assert response.status_code == 201

    organization = db_session.query(Organization).filter_by(name="Nueva Empresa").one()
    assert organization.language == "es"
    assert organization.currency_code == "EUR"


def test_changing_defaults_never_touches_existing_organizations(client, db_session):
    first = client.post(
        "/auth/register",
        json={
            "email": "existing-org-owner@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "Existing Org",
        },
    )
    assert first.status_code == 201
    existing_org = db_session.query(Organization).filter_by(name="Existing Org").one()
    assert existing_org.language == "en"
    assert existing_org.currency_code == "USD"

    admin_headers = _super_admin_headers(db_session)
    client.patch(
        "/admin/settings",
        json={
            "reason": "changing platform defaults",
            "expected_version": 1,
            "default_language": "es",
            "default_currency": "EUR",
        },
        headers=admin_headers,
    )

    db_session.refresh(existing_org)
    assert existing_org.language == "en"
    assert existing_org.currency_code == "USD"
