"""Platform-administration authorization, exercised through the real
/admin/* endpoints -- mirrors this codebase's existing
test_role_matrix.py philosophy: prove the router actually enforces the
check, not just that app.platform_permissions is internally consistent
(see test_platform_permissions.py for that, pure-logic, half)."""

from app.security import create_access_token
from tests.factories import make_user


def _auth_headers(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_user_without_platform_role_is_denied(client, db_session):
    user = make_user(db_session, email="ordinary@example.com")

    response = client.get("/admin/dashboard", headers=_auth_headers(user))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "platform_permission_denied"


def test_super_admin_is_allowed(client, db_session):
    user = make_user(db_session, email="root@example.com")
    user.platform_role = "super_admin"
    db_session.commit()

    response = client.get("/admin/dashboard", headers=_auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert "organizations_total" in body
    assert "health" in body


def test_corrupted_platform_role_is_denied_not_500(client, db_session):
    """A platform_role value that isn't a valid PlatformRole (hand-edited
    data, or a role retired in a future migration) must fail closed with
    a clean 403 -- never leak a raw ValueError as an unhandled 500."""
    user = make_user(db_session, email="corrupted@example.com")
    user.platform_role = "not_a_real_role"
    db_session.commit()

    response = client.get("/admin/dashboard", headers=_auth_headers(user))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "platform_permission_denied"


def test_every_admin_endpoint_denies_a_user_with_no_platform_role(client, db_session):
    user = make_user(db_session, email="everywhere@example.com")
    headers = _auth_headers(user)

    for path in (
        "/admin/dashboard",
        "/admin/organizations",
        "/admin/organizations/does-not-exist",
        "/admin/users",
        "/admin/users/does-not-exist",
        "/admin/system/health",
        "/admin/settings",
        "/admin/plans",
        "/admin/plans/does-not-exist",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, f"{path} should deny a non-platform-admin"


def test_organization_member_role_grants_no_platform_plan_access(client, db_session):
    """An ordinary organization member -- even an owner -- holds zero
    platform permissions; the two authorization axes (app.permissions
    vs app.platform_permissions) never leak into each other. Mirrors
    test_platform_admin_suspending_their_own_organization_loses_org_
    access_but_keeps_admin_access's converse case."""
    from tests.factories import make_org_with_owner

    owner = make_org_with_owner(db_session, email="plan-owner@example.com", org_name="Plan Co")

    response = client.get("/admin/plans", headers=owner.auth_headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "platform_permission_denied"
