"""A user who is not a member of an organization must never be able to
reach that organization's resources -- every org-scoped router is
mounted under /organizations/{organization_id}/..., and require_permission
(app/deps.py) is supposed to gate every single one of them with a
membership+permission check before any business logic runs.

This is one parametrized suite covering the read-side surface (list/get
endpoints across every resource type), rather than one file per resource,
since the assertion is identical everywhere: a foreign user gets 403, never
a 404 or 200 that would leak whether the organization/resource exists.
"""

import pytest

from tests.factories import make_org_with_owner

ENDPOINTS = [
    "/organizations/{org_id}/customers",
    "/organizations/{org_id}/products",
    "/organizations/{org_id}/invoices",
    "/organizations/{org_id}/quotes",
    "/organizations/{org_id}/dashboard",
    "/organizations/{org_id}/dashboard/insights",
    "/organizations/{org_id}/members",
    "/organizations/{org_id}/invitations",
]


@pytest.mark.parametrize("path_template", ENDPOINTS)
def test_foreign_user_cannot_read_organization_resource(client, db_session, path_template):
    org_a = make_org_with_owner(db_session, email="owner-a@example.com", org_name="Org A")
    org_b = make_org_with_owner(db_session, email="owner-b@example.com", org_name="Org B")

    response = client.get(
        path_template.format(org_id=org_a.organization.id), headers=org_b.auth_headers
    )
    assert response.status_code == 403, f"{path_template} leaked org existence: {response.text}"


@pytest.mark.parametrize("path_template", ENDPOINTS)
def test_unauthenticated_request_is_rejected(client, db_session, path_template):
    org_a = make_org_with_owner(db_session, email="owner-c@example.com", org_name="Org C")

    response = client.get(path_template.format(org_id=org_a.organization.id))
    assert response.status_code == 401


def test_foreign_user_cannot_post_customer(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-d@example.com", org_name="Org D")
    org_b = make_org_with_owner(db_session, email="owner-e@example.com", org_name="Org E")

    response = client.post(
        f"/organizations/{org_a.organization.id}/customers",
        json={"name": "Injected Customer", "email": "injected@example.com"},
        headers=org_b.auth_headers,
    )
    assert response.status_code == 403


def test_foreign_user_cannot_patch_member_role(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-f@example.com", org_name="Org F")
    org_b = make_org_with_owner(db_session, email="owner-g@example.com", org_name="Org G")

    response = client.patch(
        f"/organizations/{org_a.organization.id}/members/{org_a.membership.id}",
        json={"role": "admin"},
        headers=org_b.auth_headers,
    )
    assert response.status_code == 403
