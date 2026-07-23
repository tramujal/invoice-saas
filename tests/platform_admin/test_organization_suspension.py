from app.models import PlatformAuditLog
from tests.factories import make_org_with_owner, make_user


def _audit_rows(db_session, organization_id: str) -> list[PlatformAuditLog]:
    return (
        db_session.query(PlatformAuditLog)
        .filter_by(target_organization_id=organization_id)
        .all()
    )


def test_normal_user_cannot_suspend_or_reactivate(client, db_session):
    owner = make_org_with_owner(db_session, email="owner@example.com", org_name="Acme")
    user = make_user(db_session, email="not-an-admin@example.com")
    from app.security import create_access_token

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    suspend = client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "abuse"},
        headers=headers,
    )
    assert suspend.status_code == 403
    assert suspend.json()["detail"]["code"] == "platform_permission_denied"

    reactivate = client.post(
        f"/admin/organizations/{owner.organization.id}/reactivate",
        json={"reason": "resolved"},
        headers=headers,
    )
    assert reactivate.status_code == 403
    assert len(_audit_rows(db_session, owner.organization.id)) == 0


def test_super_admin_can_suspend_and_reactivate(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner2@example.com", org_name="Acme 2")

    suspend = client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "policy violation"},
        headers=super_admin_headers,
    )
    assert suspend.status_code == 200
    assert suspend.json()["status"] == "suspended"

    reactivate = client.post(
        f"/admin/organizations/{owner.organization.id}/reactivate",
        json={"reason": "issue resolved"},
        headers=super_admin_headers,
    )
    assert reactivate.status_code == 200
    assert reactivate.json()["status"] == "active"


def test_reason_is_mandatory(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner3@example.com", org_name="Acme 3")

    missing = client.post(
        f"/admin/organizations/{owner.organization.id}/suspend", json={}, headers=super_admin_headers
    )
    assert missing.status_code == 422

    blank = client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "   "},
        headers=super_admin_headers,
    )
    assert blank.status_code == 422
    assert len(_audit_rows(db_session, owner.organization.id)) == 0


def test_suspending_already_suspended_org_returns_conflict(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner4@example.com", org_name="Acme 4")
    client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "first"},
        headers=super_admin_headers,
    )

    again = client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "second"},
        headers=super_admin_headers,
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "organization_already_suspended"
    # Only the first, successful suspend wrote a row -- the conflicting
    # second attempt must not.
    assert len(_audit_rows(db_session, owner.organization.id)) == 1


def test_reactivating_already_active_org_returns_conflict(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner5@example.com", org_name="Acme 5")

    response = client.post(
        f"/admin/organizations/{owner.organization.id}/reactivate",
        json={"reason": "not suspended"},
        headers=super_admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "organization_already_active"
    assert len(_audit_rows(db_session, owner.organization.id)) == 0


def test_audit_log_records_exactly_one_row_per_successful_mutation(client, db_session, super_admin_headers, super_admin):
    owner = make_org_with_owner(db_session, email="owner6@example.com", org_name="Acme 6")

    client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "policy violation"},
        headers=super_admin_headers,
    )
    client.post(
        f"/admin/organizations/{owner.organization.id}/reactivate",
        json={"reason": "resolved"},
        headers=super_admin_headers,
    )

    rows = _audit_rows(db_session, owner.organization.id)
    assert len(rows) == 2
    actions = [row.action for row in rows]
    assert actions == ["organization.suspended", "organization.reactivated"]
    for row in rows:
        assert row.actor_email == super_admin.email
        assert row.target_organization_name == "Acme 6"
    assert rows[0].reason == "policy violation"
    assert rows[1].reason == "resolved"


def test_suspended_member_is_blocked_on_org_scoped_routes_even_with_prior_jwt(
    client, db_session, super_admin_headers
):
    owner = make_org_with_owner(db_session, email="owner7@example.com", org_name="Acme 7")
    # This JWT was issued while the organization was still active -- proves
    # suspension is re-checked live, never cached in the token.
    prior_headers = owner.auth_headers

    before = client.get(f"/organizations/{owner.organization.id}/dashboard", headers=prior_headers)
    assert before.status_code == 200

    client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "policy violation"},
        headers=super_admin_headers,
    )

    after = client.get(f"/organizations/{owner.organization.id}/dashboard", headers=prior_headers)
    assert after.status_code == 403
    assert after.json()["detail"]["code"] == "organization_suspended"


def test_non_member_probing_suspended_org_gets_ordinary_not_a_member_error(
    client, db_session, super_admin_headers
):
    """A non-member must never learn that a suspended org's suspension is
    *why* they're locked out -- they get the same 403 as for any other
    organization they don't belong to."""
    owner = make_org_with_owner(db_session, email="owner8@example.com", org_name="Acme 8")
    stranger = make_user(db_session, email="stranger@example.com")
    from app.security import create_access_token

    stranger_headers = {"Authorization": f"Bearer {create_access_token(stranger.id)}"}

    client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "policy violation"},
        headers=super_admin_headers,
    )

    response = client.get(
        f"/organizations/{owner.organization.id}/dashboard", headers=stranger_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "User is not a member of this organization"


def test_sibling_organization_of_same_user_remains_usable_after_suspension(
    client, db_session, super_admin_headers
):
    from tests.factories import make_membership, make_organization
    from app.membership_role import MembershipRole

    owner = make_org_with_owner(db_session, email="owner9@example.com", org_name="Acme 9")
    other_org = make_organization(db_session, name="Other Org")
    make_membership(db_session, owner.user, other_org, role=MembershipRole.owner)

    client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "policy violation"},
        headers=super_admin_headers,
    )

    blocked = client.get(
        f"/organizations/{owner.organization.id}/dashboard", headers=owner.auth_headers
    )
    assert blocked.status_code == 403

    still_ok = client.get(f"/organizations/{other_org.id}/dashboard", headers=owner.auth_headers)
    assert still_ok.status_code == 200


def test_platform_admin_reads_remain_usable_for_a_suspended_organization(
    client, db_session, super_admin_headers
):
    owner = make_org_with_owner(db_session, email="owner10@example.com", org_name="Acme 10")

    client.post(
        f"/admin/organizations/{owner.organization.id}/suspend",
        json={"reason": "policy violation"},
        headers=super_admin_headers,
    )

    detail = client.get(f"/admin/organizations/{owner.organization.id}", headers=super_admin_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "suspended"

    dashboard = client.get("/admin/dashboard", headers=super_admin_headers)
    assert dashboard.status_code == 200


def test_platform_admin_suspending_their_own_organization_loses_org_access_but_keeps_admin_access(
    client, db_session, super_admin, super_admin_headers
):
    """No special-case block exists for this -- the two authorization axes
    are independent by design (see Phase 13's architecture). The admin
    loses ordinary org-scoped access to their own org, exactly like any
    other member would, but keeps full /admin access, including the
    ability to reactivate it themselves."""
    from tests.factories import make_organization, make_membership
    from app.membership_role import MembershipRole
    from app.security import create_access_token

    org = make_organization(db_session, name="Admin's Own Org")
    make_membership(db_session, super_admin, org, role=MembershipRole.owner)
    org_member_headers = {"Authorization": f"Bearer {create_access_token(super_admin.id)}"}

    client.post(
        f"/admin/organizations/{org.id}/suspend",
        json={"reason": "self-suspend for test"},
        headers=super_admin_headers,
    )

    org_scoped = client.get(f"/organizations/{org.id}/dashboard", headers=org_member_headers)
    assert org_scoped.status_code == 403
    assert org_scoped.json()["detail"]["code"] == "organization_suspended"

    admin_detail = client.get(f"/admin/organizations/{org.id}", headers=super_admin_headers)
    assert admin_detail.status_code == 200

    reactivate = client.post(
        f"/admin/organizations/{org.id}/reactivate",
        json={"reason": "resolved"},
        headers=super_admin_headers,
    )
    assert reactivate.status_code == 200
