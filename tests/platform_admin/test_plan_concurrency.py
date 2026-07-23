"""Optimistic concurrency for Plan mutations -- mirrors
tests/platform_admin/test_settings_concurrency.py's exact structure and
rationale (see that file's own docstring for why two sequential PATCHes
sharing the same expected_version faithfully reproduce a "two admins
race to save" scenario without needing real thread-level concurrency)."""

from app.models import Plan, PlatformAuditLog


def _audit_rows(db_session):
    return db_session.query(PlatformAuditLog).filter_by(action="platform.plan_updated").all()


def test_two_updates_racing_on_the_same_expected_version_exactly_one_succeeds(
    client, db_session, super_admin_headers
):
    plan = db_session.query(Plan).filter_by(code="pro").one()

    response_a = client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "A: raise user limit", "expected_version": 1, "max_users": 100},
        headers=super_admin_headers,
    )
    response_b = client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "B: raise customer limit", "expected_version": 1, "max_customers": 20000},
        headers=super_admin_headers,
    )

    statuses = {response_a.status_code, response_b.status_code}
    assert statuses == {200, 409}

    winner, loser = (response_a, response_b) if response_a.status_code == 200 else (response_b, response_a)
    assert winner.json()["version"] == 2
    assert loser.json()["detail"]["code"] == "plan_version_conflict"

    final = client.get(f"/admin/plans/{plan.id}", headers=super_admin_headers).json()
    assert final["version"] == 2
    if winner is response_a:
        assert final["limits"]["max_users"] == 100
        assert final["limits"]["max_customers"] == 10000
    else:
        assert final["limits"]["max_customers"] == 20000
        assert final["limits"]["max_users"] == 50

    assert len(_audit_rows(db_session)) == 1


def test_conflict_changes_no_plan_fields(client, db_session, super_admin_headers):
    plan = db_session.query(Plan).filter_by(code="pro").one()

    client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "A's real change", "expected_version": 1, "max_users": 100},
        headers=super_admin_headers,
    )
    stale = client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "B's rejected change", "expected_version": 1, "max_customers": 99999},
        headers=super_admin_headers,
    )
    assert stale.status_code == 409

    current = client.get(f"/admin/plans/{plan.id}", headers=super_admin_headers).json()
    assert current["limits"]["max_users"] == 100
    assert current["limits"]["max_customers"] == 10000


def test_conflict_creates_no_audit_row(client, db_session, super_admin_headers):
    plan = db_session.query(Plan).filter_by(code="pro").one()

    client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "A's change", "expected_version": 1, "max_users": 100},
        headers=super_admin_headers,
    )
    assert len(_audit_rows(db_session)) == 1

    client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "B's rejected change", "expected_version": 1, "max_customers": 99999},
        headers=super_admin_headers,
    )

    rows = _audit_rows(db_session)
    assert len(rows) == 1
    assert rows[0].reason == "A's change"
