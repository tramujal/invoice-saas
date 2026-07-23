"""Optimistic concurrency control for PATCH /admin/settings -- proves the
atomic `UPDATE ... WHERE id = ... AND version = expected_version` (see
app.routers.platform_admin.update_platform_settings) actually rejects a
stale writer instead of silently overwriting a newer change.

The "two admins race to save" scenario is reproduced by issuing two PATCH
requests that both carry the SAME expected_version -- exactly what two
concurrent browser tabs opened from the same GET would send. Whichever
request's UPDATE statement is committed first wins and bumps the version;
the second, evaluated against the now-current row, is the one this test
suite calls "the loser." This is deterministic and requires no real
thread-level concurrency to prove: the guarantee is provided by the
database evaluating the UPDATE's WHERE clause atomically, not by anything
observable from the test's own process/thread model.
"""

from app.models import PlatformAuditLog


def _audit_rows(db_session):
    return db_session.query(PlatformAuditLog).filter_by(action="platform.settings_updated").all()


def test_stale_expected_version_returns_409_with_conflict_code(client, super_admin_headers):
    # Admin A loads the page at version 1 and saves -- version becomes 2.
    first = client.patch(
        "/admin/settings",
        json={"reason": "admin A's change", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    assert first.status_code == 200
    assert first.json()["version"] == 2

    # Admin B loaded the SAME page before A saved -- still holds version 1.
    stale = client.patch(
        "/admin/settings",
        json={"reason": "admin B's change", "expected_version": 1, "ai_enabled": False},
        headers=super_admin_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "platform_settings_version_conflict"
    assert stale.json()["detail"]["current_version"] == 2


def test_conflict_changes_no_settings(client, db_session, super_admin_headers):
    client.patch(
        "/admin/settings",
        json={"reason": "admin A's change", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )

    stale = client.patch(
        "/admin/settings",
        json={"reason": "admin B's change", "expected_version": 1, "ai_enabled": False},
        headers=super_admin_headers,
    )
    assert stale.status_code == 409

    current = client.get("/admin/settings", headers=super_admin_headers).json()
    # maintenance_mode is A's real change; ai_enabled must NOT have been
    # applied by B's rejected request.
    assert current["maintenance_mode"] is True
    assert current["ai_enabled"] is True


def test_conflict_creates_no_audit_row(client, db_session, super_admin_headers):
    client.patch(
        "/admin/settings",
        json={"reason": "admin A's change", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    assert len(_audit_rows(db_session)) == 1

    stale = client.patch(
        "/admin/settings",
        json={"reason": "admin B's change", "expected_version": 1, "ai_enabled": False},
        headers=super_admin_headers,
    )
    assert stale.status_code == 409

    # Still exactly one row -- the rejected request wrote nothing.
    rows = _audit_rows(db_session)
    assert len(rows) == 1
    assert rows[0].reason == "admin A's change"


def test_two_updates_racing_on_the_same_expected_version_exactly_one_succeeds(
    client, db_session, super_admin_headers
):
    """The "two simultaneous admins" scenario: both requests are built
    from the same GET (both carry expected_version=1). Exactly one
    succeeds, the other is rejected, the version increments exactly
    once, and neither request's change is silently dropped without a
    signal -- B's rejection IS the signal, not a lost update."""
    response_a = client.patch(
        "/admin/settings",
        json={"reason": "A: enable maintenance", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    response_b = client.patch(
        "/admin/settings",
        json={"reason": "B: disable registrations", "expected_version": 1, "registrations_enabled": False},
        headers=super_admin_headers,
    )

    statuses = {response_a.status_code, response_b.status_code}
    assert statuses == {200, 409}

    winner, loser = (response_a, response_b) if response_a.status_code == 200 else (response_b, response_a)
    assert winner.json()["version"] == 2
    assert loser.json()["detail"]["code"] == "platform_settings_version_conflict"

    final = client.get("/admin/settings", headers=super_admin_headers).json()
    assert final["version"] == 2
    # Only the winner's field actually changed.
    if winner is response_a:
        assert final["maintenance_mode"] is True
        assert final["registrations_enabled"] is True
    else:
        assert final["registrations_enabled"] is False
        assert final["maintenance_mode"] is False

    assert len(_audit_rows(db_session)) == 1


def test_successful_patch_increments_version_by_exactly_one(client, super_admin_headers):
    response = client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    assert response.json()["version"] == 2

    response2 = client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 2, "maintenance_mode": False},
        headers=super_admin_headers,
    )
    assert response2.json()["version"] == 3


def test_invalid_update_does_not_increment_version(client, super_admin_headers):
    response = client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 1, "default_language": "not-a-real-language"},
        headers=super_admin_headers,
    )
    assert response.status_code == 422

    current = client.get("/admin/settings", headers=super_admin_headers).json()
    assert current["version"] == 1
