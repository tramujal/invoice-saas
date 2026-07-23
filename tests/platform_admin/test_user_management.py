"""Phase 13E -- platform user management: disable/enable, force-verify,
admin-triggered password reset, and platform-role grant/revoke. Every
mutation is exercised through the real HTTP endpoints (not by calling
service functions directly), since the point is to prove the router
actually enforces platform.users.manage/platform.roles.manage, not that
some helper function is internally consistent."""

from app.models import PlatformAuditLog, User
from app.security import create_access_token
from tests.factories import make_user


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _make_ordinary_user_headers(db_session, email: str = "ordinary@example.com") -> dict[str, str]:
    user = make_user(db_session, email=email)
    return _headers(user)


# --- Permission gating: an ordinary (non-platform-role) user is denied
# from every single endpoint in this file. -------------------------------


def test_ordinary_user_denied_from_every_user_management_endpoint(client, db_session):
    target = make_user(db_session, email="target@example.com")
    ordinary_headers = _make_ordinary_user_headers(db_session)

    endpoints = [
        ("post", f"/admin/users/{target.id}/disable", {"reason": "test"}),
        ("post", f"/admin/users/{target.id}/enable", {"reason": "test"}),
        ("post", f"/admin/users/{target.id}/verify-email", None),
        ("post", f"/admin/users/{target.id}/send-password-reset", None),
        ("post", f"/admin/users/{target.id}/platform-role", {"role": "super_admin", "reason": "test"}),
    ]
    for method, url, body in endpoints:
        response = getattr(client, method)(url, json=body, headers=ordinary_headers)
        assert response.status_code == 403, f"{url} should be denied for an ordinary user"


# --- Disable / enable -----------------------------------------------------


def test_disable_user_succeeds_and_blocks_login(client, db_session, super_admin_headers):
    target = make_user(db_session, email="disable-me@example.com")

    response = client.post(
        f"/admin/users/{target.id}/disable", json={"reason": "policy violation"}, headers=super_admin_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    db_session.refresh(target)
    assert target.status == "disabled"

    login = client.post("/auth/login", json={"email": target.email, "password": "Correct-Horse-1"})
    assert login.status_code == 403
    assert login.json()["detail"]["code"] == "account_disabled"


def test_existing_jwt_stops_working_after_disable(client, db_session, super_admin_headers):
    target = make_user(db_session, email="stale-jwt@example.com")
    stale_headers = _headers(target)

    # Proven valid before disable.
    before = client.get("/auth/me", headers=stale_headers)
    assert before.status_code == 200

    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    after = client.get("/auth/me", headers=stale_headers)
    assert after.status_code == 401
    assert after.json()["detail"]["code"] == "account_disabled"


def test_enable_restores_access(client, db_session, super_admin_headers):
    target = make_user(db_session, email="re-enable-me@example.com")
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    response = client.post(
        f"/admin/users/{target.id}/enable", json={"reason": "resolved"}, headers=super_admin_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    login = client.post("/auth/login", json={"email": target.email, "password": "Correct-Horse-1"})
    assert login.status_code == 200


def test_repeated_disable_conflicts(client, db_session, super_admin_headers):
    target = make_user(db_session, email="double-disable@example.com")
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    second = client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "user_already_disabled"


def test_repeated_enable_conflicts(client, db_session, super_admin_headers):
    target = make_user(db_session, email="already-active@example.com")

    response = client.post(
        f"/admin/users/{target.id}/enable", json={"reason": "test"}, headers=super_admin_headers
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "user_already_active"


def test_super_admin_cannot_disable_self(client, db_session, super_admin, super_admin_headers):
    """With a second active SUPER_ADMIN present, the last-admin guard
    doesn't apply -- this isolates the self-block specifically."""
    second_admin = make_user(db_session, email="second-admin-for-self-block@example.com")
    second_admin.platform_role = "super_admin"
    db_session.commit()

    response = client.post(
        f"/admin/users/{super_admin.id}/disable", json={"reason": "test"}, headers=super_admin_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "cannot_disable_self"


def test_last_active_super_admin_cannot_be_disabled(client, super_admin, super_admin_headers):
    """super_admin is the sole active SUPER_ADMIN -- disabling themselves
    hits the last-admin guard (checked before the self-block, since it's
    the more specific of the two applicable reasons here)."""
    response = client.post(
        f"/admin/users/{super_admin.id}/disable", json={"reason": "test"}, headers=super_admin_headers
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_disable_last_super_admin"


def test_disabling_one_of_two_active_super_admins_succeeds(client, db_session, super_admin, super_admin_headers):
    """Not "the last one" -- a second active SUPER_ADMIN remains
    afterward, so this is simply an ordinary disable of someone else."""
    second_admin = make_user(db_session, email="second-admin-ok-to-disable@example.com")
    second_admin.platform_role = "super_admin"
    db_session.commit()

    response = client.post(
        f"/admin/users/{second_admin.id}/disable", json={"reason": "test"}, headers=super_admin_headers
    )
    assert response.status_code == 200


def test_disable_requires_non_empty_reason(client, db_session, super_admin_headers):
    target = make_user(db_session, email="blank-reason@example.com")
    response = client.post(f"/admin/users/{target.id}/disable", json={"reason": "   "}, headers=super_admin_headers)
    assert response.status_code == 422


# --- Force email verification ---------------------------------------------


def test_force_verify_succeeds(client, db_session, super_admin_headers):
    target = make_user(db_session, email="unverified@example.com", verified=False)
    response = client.post(f"/admin/users/{target.id}/verify-email", headers=super_admin_headers)
    assert response.status_code == 200
    assert response.json()["email_verified"] is True


def test_force_verify_already_verified_conflicts(client, db_session, super_admin_headers):
    target = make_user(db_session, email="already-verified@example.com", verified=True)
    response = client.post(f"/admin/users/{target.id}/verify-email", headers=super_admin_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_verified"


# --- Password reset ---------------------------------------------------


def test_send_password_reset_uses_existing_flow_and_never_exposes_token(
    client, db_session, super_admin_headers, fake_email_sender
):
    target = make_user(db_session, email="reset-me@example.com")
    response = client.post(f"/admin/users/{target.id}/send-password-reset", headers=super_admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert list(body.keys()) == ["message"]

    # Reuses the exact same mechanism as the public forgot-password flow --
    # an email was actually sent, and the reset link/token embedded in it
    # never appears anywhere in the API response.
    assert len(fake_email_sender.sent) == 1
    sent_message = fake_email_sender.sent[0]
    assert sent_message.to == target.email
    assert "token=" in sent_message.text_body
    assert body["message"] not in sent_message.text_body
    assert sent_message.text_body not in body["message"]


# --- Platform-role grant/revoke ---------------------------------------------


def test_grant_platform_role_succeeds_and_takes_effect_immediately(client, db_session, super_admin_headers):
    target = make_user(db_session, email="promote-me@example.com")

    response = client.post(
        f"/admin/users/{target.id}/platform-role",
        json={"role": "super_admin", "reason": "trusted operator"},
        headers=super_admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["platform_role"] == "super_admin"

    # Takes effect immediately for the target's own next request -- no
    # re-login needed, since require_platform_permission always re-reads
    # platform_role fresh from the DB.
    target_headers = _headers(target)
    me = client.get("/auth/me", headers=target_headers)
    assert me.json()["user"]["platform_role"] == "super_admin"
    dashboard = client.get("/admin/dashboard", headers=target_headers)
    assert dashboard.status_code == 200


def test_revoke_platform_role_succeeds_and_takes_effect_immediately(client, db_session, super_admin_headers):
    target = make_user(db_session, email="demote-me@example.com")
    target.platform_role = "super_admin"
    db_session.commit()
    target_headers = _headers(target)

    # Need a second super_admin to revoke this one without hitting the
    # "cannot revoke self" or "last active super_admin" guards.
    revoker = make_user(db_session, email="revoker@example.com")
    revoker.platform_role = "super_admin"
    db_session.commit()
    revoker_headers = _headers(revoker)

    response = client.post(
        f"/admin/users/{target.id}/platform-role",
        json={"role": None, "reason": "no longer needed"},
        headers=revoker_headers,
    )
    assert response.status_code == 200
    assert response.json()["platform_role"] is None

    dashboard = client.get("/admin/dashboard", headers=target_headers)
    assert dashboard.status_code == 403


def test_only_owner_of_roles_manage_can_change_platform_role(client, db_session, super_admin_headers):
    target = make_user(db_session, email="cannot-touch@example.com")
    ordinary_headers = _make_ordinary_user_headers(db_session, email="no-permission@example.com")

    response = client.post(
        f"/admin/users/{target.id}/platform-role",
        json={"role": "super_admin", "reason": "test"},
        headers=ordinary_headers,
    )
    assert response.status_code == 403


def test_self_revocation_rejected(client, db_session, super_admin, super_admin_headers):
    """With a second active SUPER_ADMIN present, the last-admin guard
    doesn't apply -- this isolates the self-block specifically."""
    second_admin = make_user(db_session, email="second-admin-for-self-revoke@example.com")
    second_admin.platform_role = "super_admin"
    db_session.commit()

    response = client.post(
        f"/admin/users/{super_admin.id}/platform-role",
        json={"role": None, "reason": "stepping down"},
        headers=super_admin_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "cannot_modify_own_platform_role"


def test_last_active_super_admin_cannot_be_revoked(client, super_admin, super_admin_headers):
    """super_admin is the sole active SUPER_ADMIN -- revoking their own
    role hits the last-admin guard (checked before the self-block)."""
    response = client.post(
        f"/admin/users/{super_admin.id}/platform-role",
        json={"role": None, "reason": "test"},
        headers=super_admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_revoke_last_super_admin"


def test_revoking_one_of_two_active_super_admins_succeeds(client, db_session, super_admin, super_admin_headers):
    """Not "the last one" -- a second active SUPER_ADMIN remains
    afterward, so this is simply an ordinary revoke of someone else."""
    second_admin = make_user(db_session, email="second-admin-ok-to-revoke@example.com")
    second_admin.platform_role = "super_admin"
    db_session.commit()

    response = client.post(
        f"/admin/users/{second_admin.id}/platform-role",
        json={"role": None, "reason": "test"},
        headers=super_admin_headers,
    )
    assert response.status_code == 200


def test_invalid_platform_role_value_fails_closed(client, db_session, super_admin_headers):
    target = make_user(db_session, email="invalid-role@example.com")
    response = client.post(
        f"/admin/users/{target.id}/platform-role",
        json={"role": "owner", "reason": "test"},
        headers=super_admin_headers,
    )
    assert response.status_code == 422


def test_organization_endpoint_cannot_modify_platform_role(client, db_session, super_admin_headers):
    """No org-scoped route (team management, invitations, etc.) has any
    parameter capable of touching platform_role at all -- confirmed here
    by exercising the ordinary org role-change endpoint against a user who
    holds a platform role, and asserting it's completely untouched."""
    from tests.factories import make_org_with_owner, make_member_in_org
    from app.membership_role import MembershipRole

    owner = make_org_with_owner(db_session, email="org-owner-for-platform-check@example.com")
    member = make_member_in_org(
        db_session, owner.organization, email="member-with-platform-role@example.com", role=MembershipRole.member
    )
    member.user.platform_role = "super_admin"
    db_session.commit()

    response = client.patch(
        f"/organizations/{owner.organization.id}/members/{member.membership.id}",
        json={"role": "admin"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 200

    db_session.refresh(member.user)
    assert member.user.platform_role == "super_admin"


# --- Audit log: exactly one row per successful mutation, none on failure ---


def test_exactly_one_audit_row_per_successful_action_and_none_on_failure(
    client, db_session, super_admin_headers
):
    target = make_user(db_session, email="audited@example.com")

    ok = client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)
    assert ok.status_code == 200

    # A repeated (failing) disable must not add a second row.
    conflict = client.post(
        f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers
    )
    assert conflict.status_code == 409

    rows = db_session.query(PlatformAuditLog).filter_by(target_user_id=target.id).all()
    assert len(rows) == 1
    assert rows[0].action == "user.disabled"
    assert rows[0].target_user_email == target.email


def test_platform_role_audit_row_stores_old_and_new_role(client, db_session, super_admin_headers):
    import json

    target = make_user(db_session, email="audited-role@example.com")
    client.post(
        f"/admin/users/{target.id}/platform-role",
        json={"role": "super_admin", "reason": "trusted"},
        headers=super_admin_headers,
    )

    row = (
        db_session.query(PlatformAuditLog)
        .filter_by(target_user_id=target.id, action="user.platform_role_granted")
        .one()
    )
    details = json.loads(row.details)
    assert details == {"old_role": None, "new_role": "super_admin"}
