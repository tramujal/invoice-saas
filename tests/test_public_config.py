"""Phase 13G -- GET /public/config: the single unauthenticated endpoint
the login/register UI polls before rendering. Deliberately minimal -- see
app.schemas.PublicConfigResponse's own docstring for why nothing beyond
maintenance_mode/registrations_enabled belongs here."""


def _super_admin_headers(db_session):
    from app.security import create_access_token
    from tests.factories import make_user

    admin = make_user(db_session, email="public-config-admin@example.com")
    admin.platform_role = "super_admin"
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def test_public_config_requires_no_authentication(client):
    response = client.get("/public/config")
    assert response.status_code == 200


def test_public_config_returns_deterministic_defaults(client):
    response = client.get("/public/config")

    assert response.status_code == 200
    assert response.json() == {"maintenance_mode": False, "registrations_enabled": True}


def test_public_config_reflects_updated_settings(client, db_session):
    admin_headers = _super_admin_headers(db_session)
    client.patch(
        "/admin/settings",
        json={
            "reason": "pausing signups",
            "expected_version": 1,
            "registrations_enabled": False,
            "maintenance_mode": True,
        },
        headers=admin_headers,
    )

    response = client.get("/public/config")

    assert response.json() == {"maintenance_mode": True, "registrations_enabled": False}


def test_public_config_exposes_only_allowlisted_fields(client, db_session):
    admin_headers = _super_admin_headers(db_session)
    client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 1, "ai_enabled": False, "default_language": "es"},
        headers=admin_headers,
    )

    response = client.get("/public/config")

    assert set(response.json().keys()) == {"maintenance_mode", "registrations_enabled"}
