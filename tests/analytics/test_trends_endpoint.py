"""GET /organizations/{organization_id}/analytics/trends -- the second
route Phase 16C adds, entirely additive alongside GET .../kpis (Phase
16B, untouched). Covers auth/permission gating, tenant isolation, the
comparison/granularity/periods/method query parameters, and the
unsupported-comparison-kind 400. Per-field correctness (each trend/series/
forecast value) is already covered by
tests/analytics/test_trend_calculators.py and test_forecast.py -- this
file only exercises the HTTP layer.
"""

from tests.factories import make_invoice, make_org_with_owner


def test_requires_authentication(client, db_session):
    org = make_org_with_owner(db_session, email="trends-auth@example.com")
    response = client.get(f"/organizations/{org.organization.id}/analytics/trends")
    assert response.status_code == 401


def test_foreign_user_cannot_read_trends(client, db_session):
    org_a = make_org_with_owner(db_session, email="trends-tenant-a@example.com")
    org_b = make_org_with_owner(db_session, email="trends-tenant-b@example.com")

    response = client.get(
        f"/organizations/{org_a.organization.id}/analytics/trends", headers=org_b.auth_headers
    )
    assert response.status_code == 403


def test_returns_trend_snapshot_for_default_comparison_and_granularity(client, db_session):
    org = make_org_with_owner(db_session, email="trends-default@example.com")
    make_invoice(db_session, org.organization, org.user)

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/trends", headers=org.auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["comparison_kind"] == "current_month"
    assert body["granularity"] == "monthly"
    assert body["revenue_trend"]["USD"]["current"] == "100.00"
    assert body["invoice_count_trend"]["current"] == "1.00"
    assert body["invoice_count_trend"]["direction"] in {"up", "down", "flat", "unknown"}
    assert isinstance(body["revenue_series"], list)
    assert isinstance(body["invoice_count_series"], list)
    assert isinstance(body["customer_count_series"], list)
    assert isinstance(body["quote_conversion_series"], list)
    assert "USD" in body["revenue_forecast"]
    assert "available" in body["invoice_count_forecast"]


def test_empty_organization_returns_empty_revenue_trend_and_zero_invoice_forecast(client, db_session):
    """No currency has ever been seen, so revenue_trend/revenue_forecast
    are correctly empty (never a fabricated USD entry). invoice_count_
    forecast, by contrast, IS available -- the default 6-month series is
    zero-filled regardless of data, so there's always >= 2 history
    points to average over; it just forecasts 0, not "unavailable" (that
    honest-gap state only occurs when fewer than 2 periods are
    requested, which the `periods` query param's own minimum blocks)."""
    org = make_org_with_owner(db_session, email="trends-empty@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/trends", headers=org.auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["revenue_trend"] == {}
    assert body["revenue_forecast"] == {}
    assert body["invoice_count_forecast"]["available"] is True
    assert body["invoice_count_forecast"]["forecast_value"] == "0.00"


def test_accepts_each_supported_comparison_kind(client, db_session):
    org = make_org_with_owner(db_session, email="trends-comparisons@example.com")
    for kind in ("current_month", "current_quarter", "current_year", "last_7_days", "last_30_days"):
        response = client.get(
            f"/organizations/{org.organization.id}/analytics/trends",
            params={"comparison": kind},
            headers=org.auth_headers,
        )
        assert response.status_code == 200, kind
        assert response.json()["comparison_kind"] == kind


def test_rejects_unsupported_comparison_kind(client, db_session):
    org = make_org_with_owner(db_session, email="trends-unsupported@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/trends",
        params={"comparison": "previous_month"},
        headers=org.auth_headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_comparison_kind"


def test_rejects_custom_comparison_kind(client, db_session):
    org = make_org_with_owner(db_session, email="trends-custom@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/trends",
        params={"comparison": "custom"},
        headers=org.auth_headers,
    )
    assert response.status_code == 400


def test_rejects_unknown_comparison_value(client, db_session):
    org = make_org_with_owner(db_session, email="trends-invalid@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/trends",
        params={"comparison": "not_a_real_value"},
        headers=org.auth_headers,
    )
    assert response.status_code == 422


def test_accepts_quarterly_and_yearly_granularity(client, db_session):
    org = make_org_with_owner(db_session, email="trends-granularity@example.com")
    make_invoice(db_session, org.organization, org.user)

    for granularity in ("quarterly", "yearly"):
        response = client.get(
            f"/organizations/{org.organization.id}/analytics/trends",
            params={"granularity": granularity},
            headers=org.auth_headers,
        )
        assert response.status_code == 200, granularity
        assert response.json()["granularity"] == granularity


def test_rejects_unknown_granularity_value(client, db_session):
    org = make_org_with_owner(db_session, email="trends-bad-granularity@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/trends",
        params={"granularity": "weekly"},
        headers=org.auth_headers,
    )
    assert response.status_code == 422


def test_accepts_explicit_periods_and_forecast_method(client, db_session):
    org = make_org_with_owner(db_session, email="trends-periods@example.com")
    make_invoice(db_session, org.organization, org.user)

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/trends",
        params={"periods": 4, "method": "linear_trend"},
        headers=org.auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["invoice_count_series"]) == 4


def test_rejects_periods_below_minimum(client, db_session):
    org = make_org_with_owner(db_session, email="trends-periods-min@example.com")

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/trends",
        params={"periods": 1},
        headers=org.auth_headers,
    )
    assert response.status_code == 422


def test_does_not_break_the_existing_kpis_endpoint(client, db_session):
    """Regression guard: Phase 16C must be purely additive -- the Phase
    16B /kpis route's shape is untouched."""
    org = make_org_with_owner(db_session, email="trends-no-regression@example.com")
    make_invoice(db_session, org.organization, org.user)

    response = client.get(
        f"/organizations/{org.organization.id}/analytics/kpis", headers=org.auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["window"]["kind"] == "current_month"
    assert body["invoice_counts"]["total"] == 1
