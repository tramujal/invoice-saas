"""H2 regression: a removed member's still-valid JWT must immediately
lose access to every org-scoped route, including ones gated only by
require_org_member (membership only, no specific permission) -- not just
the ones gated by require_permission, which already filtered on
status == active before this fix."""

from app.membership_role import MembershipRole
from tests.factories import make_member_in_org, make_org_with_owner


def test_removed_member_loses_require_org_member_gated_access(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-removal@example.com")
    member = make_member_in_org(
        db_session,
        owner.organization,
        email="removed-member@example.com",
        role=MembershipRole.member,
    )

    remove = client.post(
        f"/organizations/{owner.organization.id}/members/{member.membership.id}/remove",
        headers=owner.auth_headers,
    )
    assert remove.status_code == 200, remove.text

    # GET .../subscription is gated only by require_org_member (see
    # app.routers.billing) -- the removed member's JWT is still
    # cryptographically valid (no revocation list, no token version), so
    # this must be rejected purely on the fresh, live membership-status
    # check, not on token validity.
    response = client.get(
        f"/organizations/{owner.organization.id}/subscription",
        headers=member.auth_headers,
    )
    assert response.status_code == 403


def test_active_member_keeps_require_org_member_gated_access(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-active@example.com")
    member = make_member_in_org(
        db_session,
        owner.organization,
        email="active-member@example.com",
        role=MembershipRole.member,
    )

    response = client.get(
        f"/organizations/{owner.organization.id}/subscription",
        headers=member.auth_headers,
    )
    assert response.status_code == 200
