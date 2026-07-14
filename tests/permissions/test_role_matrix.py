"""Representative allowed/denied actions per role, exercised through the
real HTTP endpoints (not by calling check_permission directly -- that
would only prove app.permissions.ROLE_PERMISSIONS is self-consistent, not
that the routers actually call it). Every check here is driven by the
role's *permission set*, never by comparing a role string -- this is the
behavior that must keep working if a future custom role is added, per
app/permissions.py's own design goal."""

import pytest

from app.membership_role import MembershipRole
from tests.factories import make_member_in_org, make_org_with_owner


@pytest.fixture
def four_roles(db_session):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    org = owner.organization
    admin = make_member_in_org(db_session, org, email="admin@example.com", role=MembershipRole.admin)
    member = make_member_in_org(db_session, org, email="member@example.com", role=MembershipRole.member)
    viewer = make_member_in_org(db_session, org, email="viewer@example.com", role=MembershipRole.viewer)
    return {"owner": owner, "admin": admin, "member": member, "viewer": viewer}


@pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer"])
def test_every_role_can_read_customers(client, four_roles, role):
    org_id = four_roles["owner"].organization.id
    response = client.get(f"/organizations/{org_id}/customers", headers=four_roles[role].auth_headers)
    assert response.status_code == 200


@pytest.mark.parametrize("role,expected_status", [("owner", 201), ("admin", 201), ("member", 201)])
def test_write_roles_can_create_customer(client, four_roles, role, expected_status):
    org_id = four_roles["owner"].organization.id
    response = client.post(
        f"/organizations/{org_id}/customers",
        json={"name": "New Customer", "email": "new@example.com"},
        headers=four_roles[role].auth_headers,
    )
    assert response.status_code == expected_status


def test_viewer_cannot_create_customer(client, four_roles):
    org_id = four_roles["owner"].organization.id
    response = client.post(
        f"/organizations/{org_id}/customers",
        json={"name": "New Customer", "email": "new@example.com"},
        headers=four_roles["viewer"].auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_can_manage_members(client, four_roles, role):
    org_id = four_roles["owner"].organization.id
    target_id = four_roles["member"].membership.id
    response = client.patch(
        f"/organizations/{org_id}/members/{target_id}",
        json={"role": "admin"},
        headers=four_roles[role].auth_headers,
    )
    assert response.status_code == 200


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_member_and_viewer_cannot_manage_members(client, four_roles, role):
    org_id = four_roles["owner"].organization.id
    target_id = four_roles["viewer"].membership.id
    response = client.patch(
        f"/organizations/{org_id}/members/{target_id}",
        json={"role": "admin"},
        headers=four_roles[role].auth_headers,
    )
    assert response.status_code == 403


def test_only_owner_can_grant_ownership(client, four_roles):
    org_id = four_roles["owner"].organization.id
    target_id = four_roles["admin"].membership.id

    denied = client.post(
        f"/organizations/{org_id}/members/{target_id}/grant-ownership",
        json={"confirm": True},
        headers=four_roles["admin"].auth_headers,
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/organizations/{org_id}/members/{target_id}/grant-ownership",
        json={"confirm": True},
        headers=four_roles["owner"].auth_headers,
    )
    assert allowed.status_code == 200


def test_member_role_update_request_cannot_express_owner_role(client, four_roles):
    """MembershipRoleUpdateRequest.role is typed to InvitationRole, which
    excludes "owner" entirely -- this is a schema-level, not a runtime,
    guarantee that this endpoint can never be used to smuggle ownership,
    whatever the request body claims."""
    org_id = four_roles["owner"].organization.id
    target_id = four_roles["member"].membership.id
    response = client.patch(
        f"/organizations/{org_id}/members/{target_id}",
        json={"role": "owner"},
        headers=four_roles["owner"].auth_headers,
    )
    assert response.status_code == 422


def test_admin_cannot_change_owner_role(client, four_roles):
    org_id = four_roles["owner"].organization.id
    owner_membership_id = four_roles["owner"].membership.id
    response = client.patch(
        f"/organizations/{org_id}/members/{owner_membership_id}",
        json={"role": "member"},
        headers=four_roles["admin"].auth_headers,
    )
    assert response.status_code == 403


def test_last_owner_cannot_be_demoted(client, db_session):
    solo_owner = make_org_with_owner(db_session, email="solo@example.com")
    org_id = solo_owner.organization.id

    response = client.patch(
        f"/organizations/{org_id}/members/{solo_owner.membership.id}",
        json={"role": "member"},
        headers=solo_owner.auth_headers,
    )
    assert response.status_code == 409


def test_last_owner_cannot_be_removed(client, db_session):
    solo_owner = make_org_with_owner(db_session, email="solo2@example.com")
    org_id = solo_owner.organization.id

    response = client.post(
        f"/organizations/{org_id}/members/{solo_owner.membership.id}/remove",
        headers=solo_owner.auth_headers,
    )
    assert response.status_code == 409


def test_last_owner_can_be_demoted_once_a_second_owner_exists(client, db_session):
    first_owner = make_org_with_owner(db_session, email="first@example.com")
    org = first_owner.organization
    second_owner = make_member_in_org(
        db_session, org, email="second@example.com", role=MembershipRole.owner
    )

    response = client.patch(
        f"/organizations/{org.id}/members/{first_owner.membership.id}",
        json={"role": "member"},
        headers=second_owner.auth_headers,
    )
    assert response.status_code == 200
