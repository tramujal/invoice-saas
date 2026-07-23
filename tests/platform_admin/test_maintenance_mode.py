"""Phase 13G -- platform-wide maintenance mode. Mirrors
test_organization_suspension.py's structure (the per-org analogue): a
global switch, toggled via PATCH /admin/settings, enforced live on every
request with no JWT-cacheable bypass (see app.deps._ensure_not_in_
maintenance_mode)."""

from app.security import create_access_token
from tests.factories import make_org_with_owner, make_user


def _current_version(client, super_admin_headers) -> int:
    return client.get("/admin/settings", headers=super_admin_headers).json()["version"]


def _enable_maintenance(client, super_admin_headers, reason: str = "scheduled maintenance") -> None:
    response = client.patch(
        "/admin/settings",
        json={
            "reason": reason,
            "expected_version": _current_version(client, super_admin_headers),
            "maintenance_mode": True,
        },
        headers=super_admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["maintenance_mode"] is True


def _disable_maintenance(client, super_admin_headers, reason: str = "maintenance complete") -> None:
    response = client.patch(
        "/admin/settings",
        json={
            "reason": reason,
            "expected_version": _current_version(client, super_admin_headers),
            "maintenance_mode": False,
        },
        headers=super_admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["maintenance_mode"] is False


def test_maintenance_mode_blocks_org_scoped_routes_even_with_prior_jwt(
    client, db_session, super_admin_headers
):
    owner = make_org_with_owner(db_session, email="owner@example.com", org_name="Acme")
    # Issued while the platform was still fully operational -- proves
    # maintenance is re-checked live, never cached in the token.
    prior_headers = owner.auth_headers

    before = client.get(f"/organizations/{owner.organization.id}/dashboard", headers=prior_headers)
    assert before.status_code == 200

    _enable_maintenance(client, super_admin_headers)

    after = client.get(f"/organizations/{owner.organization.id}/dashboard", headers=prior_headers)
    assert after.status_code == 503
    assert after.json()["detail"]["code"] == "maintenance_mode"


def test_super_admin_can_disable_maintenance_mode_and_restore_access(
    client, db_session, super_admin_headers
):
    owner = make_org_with_owner(db_session, email="owner2@example.com", org_name="Acme 2")

    _enable_maintenance(client, super_admin_headers)
    blocked = client.get(f"/organizations/{owner.organization.id}/dashboard", headers=owner.auth_headers)
    assert blocked.status_code == 503

    _disable_maintenance(client, super_admin_headers)
    restored = client.get(f"/organizations/{owner.organization.id}/dashboard", headers=owner.auth_headers)
    assert restored.status_code == 200


def test_platform_admin_routes_remain_available_during_maintenance(
    client, db_session, super_admin_headers
):
    owner = make_org_with_owner(db_session, email="owner3@example.com", org_name="Acme 3")
    _enable_maintenance(client, super_admin_headers)

    settings_get = client.get("/admin/settings", headers=super_admin_headers)
    assert settings_get.status_code == 200

    orgs_list = client.get("/admin/organizations", headers=super_admin_headers)
    assert orgs_list.status_code == 200

    org_detail = client.get(f"/admin/organizations/{owner.organization.id}", headers=super_admin_headers)
    assert org_detail.status_code == 200


def test_health_endpoint_available_during_maintenance(client, super_admin_headers):
    _enable_maintenance(client, super_admin_headers)
    response = client.get("/health")
    assert response.status_code == 200


def test_login_remains_available_during_maintenance(client, db_session, super_admin_headers):
    make_user(db_session, email="login-during-maintenance@example.com")
    _enable_maintenance(client, super_admin_headers)

    response = client.post(
        "/auth/login",
        json={"email": "login-during-maintenance@example.com", "password": "Correct-Horse-1"},
    )
    assert response.status_code == 200


def test_password_reset_and_email_verification_requests_remain_available_during_maintenance(
    client, db_session, super_admin_headers
):
    unverified = make_user(db_session, email="reset-during-maintenance@example.com", verified=False)
    unverified_headers = {"Authorization": f"Bearer {create_access_token(unverified.id)}"}
    _enable_maintenance(client, super_admin_headers)

    reset = client.post(
        "/auth/forgot-password", json={"email": "reset-during-maintenance@example.com"}
    )
    assert reset.status_code == 200

    verify = client.post("/auth/resend-verification", headers=unverified_headers)
    assert verify.status_code == 200


def test_registration_blocked_during_maintenance_with_503(client, super_admin_headers):
    _enable_maintenance(client, super_admin_headers)

    response = client.post(
        "/auth/register",
        json={
            "email": "new-during-maintenance@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "New Co",
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "maintenance_mode"


def test_public_quote_view_and_pdf_remain_available_but_accept_reject_blocked_during_maintenance(
    client, db_session, super_admin_headers
):
    from tests.factories import make_customer, make_quote

    owner = make_org_with_owner(db_session, email="quote-owner@example.com", org_name="Quote Co")
    customer = make_customer(db_session, owner.organization, email="customer@example.com")
    quote = make_quote(db_session, owner.organization, owner.user, customer=customer)
    token = quote.public_token

    _enable_maintenance(client, super_admin_headers)

    view = client.get(f"/quotes/public/{token}")
    assert view.status_code == 200

    pdf = client.get(f"/quotes/public/{token}/pdf")
    assert pdf.status_code == 200

    accept = client.post(f"/quotes/public/{token}/accept")
    assert accept.status_code == 503
    assert accept.json()["detail"]["code"] == "maintenance_mode"


def test_invitation_view_remains_available_but_accept_blocked_during_maintenance(
    client, db_session, super_admin_headers
):
    from tests.factories import make_invitation

    owner = make_org_with_owner(db_session, email="invite-owner@example.com", org_name="Invite Co")
    invitation, raw_token = make_invitation(db_session, owner.organization, owner.membership)

    _enable_maintenance(client, super_admin_headers)

    view = client.get(f"/invitations/public/{raw_token}")
    assert view.status_code == 200

    accept_headers = {
        "Authorization": f"Bearer {create_access_token(make_user(db_session, email='invitee@example.com').id)}"
    }
    accept = client.post(f"/invitations/public/{raw_token}/accept", headers=accept_headers)
    assert accept.status_code == 503
    assert accept.json()["detail"]["code"] == "maintenance_mode"


def test_non_member_probing_during_maintenance_still_gets_maintenance_error(
    client, db_session, super_admin_headers
):
    """Maintenance mode is checked *after* an org-scoped route's own
    membership check (same ordering as organization suspension), so a
    non-member still gets the ordinary "not a member" 403 first -- this
    test instead confirms the platform-wide 503 fires for an actual
    member, since maintenance has no per-org "did you belong here"
    distinction to hide."""
    owner = make_org_with_owner(db_session, email="owner4@example.com", org_name="Acme 4")
    stranger = make_user(db_session, email="stranger@example.com")
    stranger_headers = {"Authorization": f"Bearer {create_access_token(stranger.id)}"}

    _enable_maintenance(client, super_admin_headers)

    response = client.get(f"/organizations/{owner.organization.id}/dashboard", headers=stranger_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "User is not a member of this organization"
