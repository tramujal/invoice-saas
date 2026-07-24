"""Representative allowed/denied actions per role, exercised through the
real HTTP endpoints (not by calling check_permission directly -- that
would only prove app.permissions.ROLE_PERMISSIONS is self-consistent, not
that the routers actually call it). Every check here is driven by the
role's *permission set*, never by comparing a role string -- this is the
behavior that must keep working if a future custom role is added, per
app/permissions.py's own design goal.

Role-hierarchy tests (who may manage/assign which role relative to their
own rank -- viewer < member < admin < owner) live here too, exercised the
same way through the real endpoints; see tests/permissions/
test_role_hierarchy.py for the pure app.role_hierarchy unit tests."""

import pytest

from app.membership_role import MembershipRole
from app.models import PLAN_ID_ENTERPRISE
from tests.factories import make_member_in_org, make_org_with_owner


@pytest.fixture
def four_roles(db_session):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    org = owner.organization
    # This fixture tests the permission system, an axis entirely
    # independent of plan limits (Phase 14C) -- on the Free plan's
    # default 2-user cap, the 4 members created here (plus whichever
    # test invites a 5th to test who's *allowed* to invite) would
    # incidentally hit the user limit and fail for the wrong reason.
    # Enterprise's unlimited users keeps this fixture testing only what
    # it says it tests.
    org.plan_id = PLAN_ID_ENTERPRISE
    db_session.commit()
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


def test_admin_can_change_viewer_to_member_and_back(client, four_roles):
    org_id = four_roles["owner"].organization.id
    target_id = four_roles["viewer"].membership.id

    up = client.patch(
        f"/organizations/{org_id}/members/{target_id}",
        json={"role": "member"},
        headers=four_roles["admin"].auth_headers,
    )
    assert up.status_code == 200
    assert up.json()["role"] == "member"

    down = client.patch(
        f"/organizations/{org_id}/members/{target_id}",
        json={"role": "viewer"},
        headers=four_roles["admin"].auth_headers,
    )
    assert down.status_code == 200
    assert down.json()["role"] == "viewer"


def test_admin_cannot_assign_admin_role(client, four_roles):
    org_id = four_roles["owner"].organization.id
    target_id = four_roles["member"].membership.id
    response = client.patch(
        f"/organizations/{org_id}/members/{target_id}",
        json={"role": "admin"},
        headers=four_roles["admin"].auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "role_assignment_not_allowed"


def test_admin_cannot_modify_another_admin(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-aa@example.com")
    org = owner.organization
    admin_one = make_member_in_org(db_session, org, email="admin-one@example.com", role=MembershipRole.admin)
    admin_two = make_member_in_org(db_session, org, email="admin-two@example.com", role=MembershipRole.admin)

    response = client.patch(
        f"/organizations/{org.id}/members/{admin_two.membership.id}",
        json={"role": "member"},
        headers=admin_one.auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_role_authority"


def test_admin_cannot_remove_another_admin(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-ar@example.com")
    org = owner.organization
    admin_one = make_member_in_org(db_session, org, email="admin-one-r@example.com", role=MembershipRole.admin)
    admin_two = make_member_in_org(db_session, org, email="admin-two-r@example.com", role=MembershipRole.admin)

    response = client.post(
        f"/organizations/{org.id}/members/{admin_two.membership.id}/remove",
        headers=admin_one.auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_role_authority"


def test_admin_cannot_change_owner_role(client, four_roles):
    org_id = four_roles["owner"].organization.id
    owner_membership_id = four_roles["owner"].membership.id
    response = client.patch(
        f"/organizations/{org_id}/members/{owner_membership_id}",
        json={"role": "member"},
        headers=four_roles["admin"].auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_role_authority"


def test_admin_cannot_remove_owner(client, four_roles):
    org_id = four_roles["owner"].organization.id
    owner_membership_id = four_roles["owner"].membership.id
    response = client.post(
        f"/organizations/{org_id}/members/{owner_membership_id}/remove",
        headers=four_roles["admin"].auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_role_authority"


@pytest.mark.parametrize("target_role,new_role", [("admin", "member"), ("member", "admin"), ("viewer", "admin")])
def test_owner_can_assign_admin_member_viewer(client, four_roles, target_role, new_role):
    org_id = four_roles["owner"].organization.id
    target_id = four_roles[target_role].membership.id
    response = client.patch(
        f"/organizations/{org_id}/members/{target_id}",
        json={"role": new_role},
        headers=four_roles["owner"].auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["role"] == new_role


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


def test_owner_cannot_promote_self_to_owner_again(client, four_roles):
    """Every reachable caller of grant-ownership is already an owner, so
    this would be a no-op in practice -- rejected anyway, since "a user
    may never promote themselves" is an absolute rule with no no-op
    exception (see SelfPromotionError)."""
    org_id = four_roles["owner"].organization.id
    self_id = four_roles["owner"].membership.id
    response = client.post(
        f"/organizations/{org_id}/members/{self_id}/grant-ownership",
        json={"confirm": True},
        headers=four_roles["owner"].auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "self_promotion_not_allowed"


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


def test_admin_cannot_invite_admin(client, four_roles):
    org_id = four_roles["owner"].organization.id
    response = client.post(
        f"/organizations/{org_id}/invitations",
        json={"email": "new-admin@example.com", "role": "admin"},
        headers=four_roles["admin"].auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "role_assignment_not_allowed"


def test_admin_can_invite_member_and_viewer(client, four_roles):
    org_id = four_roles["owner"].organization.id
    for role, email in (("member", "new-member@example.com"), ("viewer", "new-viewer@example.com")):
        response = client.post(
            f"/organizations/{org_id}/invitations",
            json={"email": email, "role": role},
            headers=four_roles["admin"].auth_headers,
        )
        assert response.status_code == 201, response.text


def test_owner_can_invite_admin(client, four_roles):
    org_id = four_roles["owner"].organization.id
    response = client.post(
        f"/organizations/{org_id}/invitations",
        json={"email": "new-admin2@example.com", "role": "admin"},
        headers=four_roles["owner"].auth_headers,
    )
    assert response.status_code == 201, response.text


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


def test_last_active_owner_cannot_self_demote(client, db_session):
    """Explicit regression for the Phase 13D.1 pre-check: a solo owner
    hitting their own PATCH /members/{self} with a lower role is exactly
    "self-demote," and must be blocked the same as any other last-owner
    demotion -- self-targeting only exempts the rank-hierarchy check
    (can_manage_member), never the last-owner headcount invariant."""
    solo_owner = make_org_with_owner(db_session, email="solo-self-demote@example.com")
    org_id = solo_owner.organization.id

    response = client.patch(
        f"/organizations/{org_id}/members/{solo_owner.membership.id}",
        json={"role": "viewer"},
        headers=solo_owner.auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_remove_last_owner"


def test_last_active_owner_cannot_leave(client, db_session):
    """Explicit regression for the Phase 13D.1 pre-check: there is no
    dedicated "leave organization" endpoint -- POST /members/{self}/remove
    is how a member voluntarily exits (see test_admin_can_remove_self) --
    so leaving-as-the-last-owner must hit the exact same last-owner guard
    a third party's removal attempt would."""
    solo_owner = make_org_with_owner(db_session, email="solo-leave@example.com")
    org_id = solo_owner.organization.id

    response = client.post(
        f"/organizations/{org_id}/members/{solo_owner.membership.id}/remove",
        headers=solo_owner.auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_remove_last_owner"


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


def test_admin_can_remove_self(client, four_roles):
    """Self-modification is exempt from the "another user" hierarchy
    rule -- an admin may remove their own membership (there being no
    dedicated "leave organization" endpoint, /remove is how a member
    voluntarily exits)."""
    org_id = four_roles["owner"].organization.id
    response = client.post(
        f"/organizations/{org_id}/members/{four_roles['admin'].membership.id}/remove",
        headers=four_roles["admin"].auth_headers,
    )
    assert response.status_code == 200


def test_corrupted_actor_role_fails_closed(client, db_session):
    """A hand-edited/corrupted role value on the ACTOR's own membership
    row must be denied (403), never surfaced as an unhandled 500."""
    owner = make_org_with_owner(db_session, email="corrupt-actor@example.com")
    member = make_member_in_org(db_session, owner.organization, email="corrupt-member@example.com")
    member.membership.role = "not_a_real_role"
    db_session.commit()

    response = client.get(f"/organizations/{owner.organization.id}/customers", headers=member.auth_headers)
    assert response.status_code == 403


def test_corrupted_target_role_fails_closed(client, db_session):
    """A hand-edited/corrupted role value on the TARGET's membership row
    must block every attempt to manage it (403), never a 500 -- the safe
    direction to fail closed, since a corrupted value must never look
    like a low-rank, freely-manageable role."""
    owner = make_org_with_owner(db_session, email="corrupt-target@example.com")
    target = make_member_in_org(db_session, owner.organization, email="corrupt-target-member@example.com")
    target.membership.role = "not_a_real_role"
    db_session.commit()

    response = client.patch(
        f"/organizations/{owner.organization.id}/members/{target.membership.id}",
        json={"role": "viewer"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_role_authority"


def test_no_organization_endpoint_can_modify_platform_role(client, db_session):
    """Organization role management must never touch platform_role --
    the two authorization axes (org-scoped roles vs. platform admin) are
    completely independent by construction."""
    owner = make_org_with_owner(db_session, email="platform-independent-owner@example.com")
    member = make_member_in_org(db_session, owner.organization, email="platform-independent-member@example.com")
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
