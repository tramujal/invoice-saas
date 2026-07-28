"""GET /organizations/{organization_id}/analytics/kpis -- the one new
route this phase adds. Covers auth/permission gating, tenant isolation,
the window query parameter, and the custom-window 400. Endpoint-shape
correctness (each field's own values) is already covered by the
calculator/service tests -- this file only exercises the HTTP layer.
"""

from tests.factories import make_invoice, make_org_with_owner


def test_requires_authentication(client, db_session):
    org = make_org_with_owner(db_session, email="kpi-auth@example.com")
    response = client.get(f"/organizations/{org.organization.id}/analytics/kpis")
    assert response.status_code == 401


def test_foreign_user_cannot_read_kpis(client, db_session):
    org_a = make_org_with_owner(db_session, email="kpi-tenant-a@example.com")
    org_b = make_org_with_owner(db_session, email="kpi-tenant-b@example.com")

    response = client.get(
        f"/organizations/{org_a.organization.id}/analytics/kpis", headers=org_b.auth_headers
    )
    assert response.status_code == 403


def test_returns_kpi_snapshot_for_default_window(client, db_session):
    org = make_org_with_owner(db_session, email="kpi-default@example.com")
    make_invoice(db_session, org.organization, org.user)

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/kpis", headers=org.auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["window"]["kind"] == "current_month"
    assert body["invoice_counts"]["total"] == 1
    assert body["revenue_by_currency"]["USD"] == "100.00"
    assert body["average_payment_time"]["available"] is False


def test_accepts_a_different_window_kind(client, db_session):
    org = make_org_with_owner(db_session, email="kpi-window@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/kpis",
        params={"window": "last_7_days"},
        headers=org.auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["window"]["kind"] == "last_7_days"


def test_rejects_unsupported_custom_window(client, db_session):
    org = make_org_with_owner(db_session, email="kpi-custom@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/kpis",
        params={"window": "custom"},
        headers=org.auth_headers,
    )
    assert response.status_code == 400


def test_rejects_unknown_window_value(client, db_session):
    org = make_org_with_owner(db_session, email="kpi-invalid@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/kpis",
        params={"window": "not_a_real_window"},
        headers=org.auth_headers,
    )
    assert response.status_code == 422
