from tests.factories import make_customer, make_invoice, make_org_with_owner, make_quote


def test_dashboard_totals_reflect_seeded_data(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner@example.com", org_name="Acme")
    customer = make_customer(db_session, owner.organization)
    make_invoice(db_session, owner.organization, owner.user, customer=customer)
    make_quote(db_session, owner.organization, owner.user, customer=customer)

    response = client.get("/admin/dashboard", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["organizations_total"] >= 1
    assert body["users_total"] >= 2  # the seeded owner + the super_admin fixture's own user
    assert body["invoices_total"] >= 1
    assert body["quotes_total"] >= 1
    assert body["customers_total"] >= 1
    assert "health" in body
    assert body["health"]["database_reachable"] is True


def test_dashboard_requires_dashboard_view_permission(client, db_session):
    """A user with no platform_role at all is denied -- the fuller sweep
    across every /admin/* endpoint lives in
    tests/permissions/test_platform_role_matrix.py; this just confirms
    the dashboard specifically."""
    from app.security import create_access_token
    from tests.factories import make_user

    user = make_user(db_session, email="not-an-admin@example.com")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    response = client.get("/admin/dashboard", headers=headers)

    assert response.status_code == 403
