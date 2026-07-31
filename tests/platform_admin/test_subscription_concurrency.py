"""Optimistic concurrency for the platform-admin Subscription mutation
endpoints (Phase P2.1) -- mirrors test_plan_concurrency.py's exact
structure: two sequential HTTP calls sharing the same expected_version
faithfully reproduce a "two admins race to save" scenario without real
thread-level concurrency (see that file's own docstring). A genuine,
multi-connection race -- including the specific admin-vs-webhook
scenario Phase P2.1 was written to close -- is covered instead at the
service layer in tests/billing/test_subscription_concurrency.py, since
that's the layer BillingService's version_id_col protection actually
lives at; these tests only exercise the router's own early,
client-supplied-expected_version staleness check.

Unlike Plan/PlatformSettings, expected_version is OPTIONAL here (see
OrganizationPlanChangeRequest's own comment in app.schemas) -- these
tests also cover that a request omitting it still succeeds."""

from app.models import Plan, PlatformAuditLog, Subscription
from tests.factories import make_organization, make_plan


def _audit_rows(db_session, action: str):
    return db_session.query(PlatformAuditLog).filter_by(action=action).all()


def _subscription_for(db_session, organization) -> Subscription:
    return db_session.query(Subscription).filter_by(organization_id=organization.id).one()


def test_two_change_plan_requests_racing_on_the_same_expected_version_exactly_one_succeeds(
    client, db_session, super_admin_headers
):
    organization = make_organization(db_session, name="Sub Concurrency Co")
    plan_b = make_plan(db_session, code="sub-conc-b", sort_order=1)
    plan_c = make_plan(db_session, code="sub-conc-c", sort_order=2)
    subscription = _subscription_for(db_session, organization)
    assert subscription.version == 1

    response_a = client.post(
        f"/admin/subscriptions/{subscription.id}/change-plan",
        json={"plan_id": plan_b.id, "reason": "A: move to B", "expected_version": 1},
        headers=super_admin_headers,
    )
    response_b = client.post(
        f"/admin/subscriptions/{subscription.id}/change-plan",
        json={"plan_id": plan_c.id, "reason": "B: move to C", "expected_version": 1},
        headers=super_admin_headers,
    )

    statuses = {response_a.status_code, response_b.status_code}
    assert statuses == {200, 409}

    winner, loser = (response_a, response_b) if response_a.status_code == 200 else (response_b, response_a)
    assert loser.json()["detail"]["code"] == "subscription_version_conflict"

    final = client.get(f"/admin/subscriptions/{subscription.id}", headers=super_admin_headers).json()
    if winner is response_a:
        assert final["plan"]["code"] == "sub-conc-b"
    else:
        assert final["plan"]["code"] == "sub-conc-c"

    assert len(_audit_rows(db_session, "subscription.plan_changed")) == 1


def test_stale_expected_version_on_cancel_never_applies_and_writes_no_audit_row(
    client, db_session, super_admin_headers
):
    organization = make_organization(db_session, name="Sub Concurrency Cancel Co")
    plan_b = make_plan(db_session, code="sub-conc-cancel-b", sort_order=1)
    subscription = _subscription_for(db_session, organization)

    # A genuine version-advancing write happens first (the plan change),
    # so the cancel below's expected_version=1 is now stale.
    client.post(
        f"/admin/subscriptions/{subscription.id}/change-plan",
        json={"plan_id": plan_b.id, "reason": "advance the version first"},
        headers=super_admin_headers,
    )

    stale = client.post(
        f"/admin/subscriptions/{subscription.id}/cancel",
        json={"reason": "should be rejected", "expected_version": 1},
        headers=super_admin_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "subscription_version_conflict"

    current = client.get(f"/admin/subscriptions/{subscription.id}", headers=super_admin_headers).json()
    assert current["status"] == "active"
    assert len(_audit_rows(db_session, "subscription.canceled")) == 0


def test_omitting_expected_version_still_succeeds_backward_compatible(
    client, db_session, super_admin_headers
):
    """expected_version is optional (unlike Plan/PlatformSettings) --
    an existing caller that never sends it must keep working exactly as
    it did before Phase P2.1."""
    organization = make_organization(db_session, name="Sub Concurrency Compat Co")
    subscription = _subscription_for(db_session, organization)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/cancel",
        json={"reason": "no expected_version supplied"},
        headers=super_admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"


def test_organization_plan_endpoint_stale_expected_version_returns_409(
    client, db_session, super_admin_headers
):
    organization = make_organization(db_session, name="Sub Concurrency Org Plan Co")
    plan_b = make_plan(db_session, code="sub-conc-orgplan-b", sort_order=1)
    plan_c = make_plan(db_session, code="sub-conc-orgplan-c", sort_order=2)
    subscription = _subscription_for(db_session, organization)

    first = client.patch(
        f"/admin/organizations/{organization.id}/plan",
        json={"plan_id": plan_b.id, "reason": "first change", "expected_version": 1},
        headers=super_admin_headers,
    )
    assert first.status_code == 200

    stale = client.patch(
        f"/admin/organizations/{organization.id}/plan",
        json={"plan_id": plan_c.id, "reason": "stale second change", "expected_version": 1},
        headers=super_admin_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "subscription_version_conflict"
