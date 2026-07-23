"""Phase 13F -- GET /admin/audit-log: permission gating, pagination,
every filter, sanitization, and the "one row per success, none on
failure" regression sweep across every existing platform mutation."""

import json

from app.models import Organization, OrganizationMember, PlatformAuditLog, User
from app.security import create_access_token
from tests.factories import make_org_with_owner, make_user


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_ordinary_user_denied(client, db_session):
    ordinary = make_user(db_session, email="ordinary-audit@example.com")
    response = client.get("/admin/audit-log", headers=_headers(ordinary))
    assert response.status_code == 403


def test_super_admin_allowed(client, super_admin_headers):
    response = client.get("/admin/audit-log", headers=super_admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert "total" in body and "items" in body


def test_no_mutation_route_exists(client, super_admin_headers):
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/admin/audit-log", headers=super_admin_headers)
        assert response.status_code == 405
    # No detail endpoint either -- a single list endpoint is sufficient.
    detail_response = client.get("/admin/audit-log/some-id", headers=super_admin_headers)
    assert detail_response.status_code == 404


def test_pagination_and_deterministic_ordering(client, db_session, super_admin_headers):
    org = Organization(name="Pagination Org")
    db_session.add(org)
    db_session.commit()

    for i in range(5):
        client.post(
            f"/admin/organizations/{org.id}/suspend" if i % 2 == 0 else f"/admin/organizations/{org.id}/reactivate",
            json={"reason": f"reason {i}"},
            headers=super_admin_headers,
        )

    first_page = client.get("/admin/audit-log?limit=2&offset=0", headers=super_admin_headers).json()
    second_page = client.get("/admin/audit-log?limit=2&offset=2", headers=super_admin_headers).json()
    assert first_page["total"] == second_page["total"] == 5
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 2
    # No overlap between pages, confirming stable created_at DESC, id DESC
    # ordering rather than an unstable default order.
    first_ids = {item["id"] for item in first_page["items"]}
    second_ids = {item["id"] for item in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)

    all_items = client.get("/admin/audit-log?limit=100", headers=super_admin_headers).json()["items"]
    timestamps = [item["created_at"] for item in all_items]
    assert timestamps == sorted(timestamps, reverse=True)


def test_filter_by_action(client, db_session, super_admin_headers):
    target = make_user(db_session, email="filter-action@example.com")
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)
    client.post(f"/admin/users/{target.id}/enable", json={"reason": "test"}, headers=super_admin_headers)

    response = client.get("/admin/audit-log?action=user.disabled", headers=super_admin_headers)
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "user.disabled"


def test_filter_by_actor_user_id_and_email(client, db_session, super_admin_headers, super_admin):
    target = make_user(db_session, email="filter-actor@example.com")
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    by_id = client.get(f"/admin/audit-log?actor_user_id={super_admin.id}", headers=super_admin_headers).json()
    assert by_id["total"] >= 1
    assert all(item["actor_user_id"] == super_admin.id for item in by_id["items"])

    by_email = client.get("/admin/audit-log?actor_email=super-admin", headers=super_admin_headers).json()
    assert by_email["total"] >= 1
    assert all("super-admin" in item["actor_email"] for item in by_email["items"])

    no_match = client.get("/admin/audit-log?actor_email=nobody-matches-this", headers=super_admin_headers).json()
    assert no_match["total"] == 0
    assert no_match["items"] == []


def test_filter_by_target_organization_id(client, db_session, super_admin_headers):
    org = Organization(name="Target Org Filter")
    db_session.add(org)
    db_session.commit()
    client.post(f"/admin/organizations/{org.id}/suspend", json={"reason": "test"}, headers=super_admin_headers)

    other_org = Organization(name="Other Org")
    db_session.add(other_org)
    db_session.commit()
    client.post(f"/admin/organizations/{other_org.id}/suspend", json={"reason": "test"}, headers=super_admin_headers)

    response = client.get(f"/admin/audit-log?target_organization_id={org.id}", headers=super_admin_headers)
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["target_organization_id"] == org.id


def test_filter_by_target_user_id(client, db_session, super_admin_headers):
    target = make_user(db_session, email="target-filter@example.com")
    other = make_user(db_session, email="other-target-filter@example.com")
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)
    client.post(f"/admin/users/{other.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    response = client.get(f"/admin/audit-log?target_user_id={target.id}", headers=super_admin_headers)
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["target_user_id"] == target.id


def test_filter_by_target_search_matches_org_name_or_user_email(client, db_session, super_admin_headers):
    org = Organization(name="Searchable Org Name")
    db_session.add(org)
    db_session.commit()
    client.post(f"/admin/organizations/{org.id}/suspend", json={"reason": "test"}, headers=super_admin_headers)

    user = make_user(db_session, email="searchable-target@example.com")
    client.post(f"/admin/users/{user.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    by_org_name = client.get("/admin/audit-log?target_search=Searchable Org", headers=super_admin_headers).json()
    assert by_org_name["total"] == 1
    assert by_org_name["items"][0]["target_organization_name"] == "Searchable Org Name"

    by_user_email = client.get("/admin/audit-log?target_search=searchable-target", headers=super_admin_headers).json()
    assert by_user_email["total"] == 1
    assert by_user_email["items"][0]["target_user_email"] == "searchable-target@example.com"


def test_filter_by_date_range(client, db_session, super_admin_headers):
    from datetime import datetime, timedelta, timezone

    target = make_user(db_session, email="date-range@example.com")
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    row = db_session.query(PlatformAuditLog).filter_by(target_user_id=target.id).one()
    today = datetime.now(timezone.utc).date()

    in_range = client.get(
        f"/admin/audit-log?date_from={today}&date_to={today}", headers=super_admin_headers
    ).json()
    assert any(item["id"] == row.id for item in in_range["items"])

    tomorrow = today + timedelta(days=1)
    out_of_range = client.get(
        f"/admin/audit-log?date_from={tomorrow}&date_to={tomorrow}", headers=super_admin_headers
    ).json()
    assert all(item["id"] != row.id for item in out_of_range["items"])


def test_invalid_date_range_rejected(client, super_admin_headers):
    response = client.get(
        "/admin/audit-log?date_from=2026-06-01&date_to=2026-01-01", headers=super_admin_headers
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_date_range"


def test_snapshots_survive_organization_deletion(client, db_session, super_admin_headers):
    org = Organization(name="Doomed Org", business_name="Doomed Org Business")
    db_session.add(org)
    db_session.commit()
    client.post(f"/admin/organizations/{org.id}/suspend", json={"reason": "test"}, headers=super_admin_headers)

    org_id = org.id
    db_session.delete(org)
    db_session.commit()

    response = client.get(f"/admin/audit-log?action=organization.suspended", headers=super_admin_headers)
    matching = [item for item in response.json()["items"] if item["target_organization_name"] == "Doomed Org Business"]
    assert len(matching) == 1
    # The FK is ON DELETE SET NULL -- the live id reference is gone, but
    # the name snapshot survives, which is the entire point of storing it.
    assert matching[0]["target_organization_id"] is None
    assert org_id  # sanity: we did have a real id before deletion


def test_snapshots_survive_user_deletion(client, db_session, super_admin_headers):
    target = make_user(db_session, email="doomed-user@example.com")
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    db_session.delete(target)
    db_session.commit()

    response = client.get("/admin/audit-log?action=user.disabled", headers=super_admin_headers)
    matching = [item for item in response.json()["items"] if item["target_user_email"] == "doomed-user@example.com"]
    assert len(matching) == 1
    assert matching[0]["target_user_id"] is None


def test_sensitive_details_keys_are_recursively_redacted(client, db_session, super_admin_headers):
    row = PlatformAuditLog(
        actor_user_id=None,
        actor_email="synthetic@example.com",
        action="user.platform_role_granted",
        target_user_email="synthetic-target@example.com",
        reason="synthetic row for redaction test",
        details=json.dumps(
            {
                "old_role": None,
                "new_role": "super_admin",
                "nested": {"api_key": "sk-live-abc123", "Authorization": "Bearer xyz"},
                "reset_token": "raw-token-value",
                "password_hash": "bcrypt$...",
                "cookie": "session=abc",
            }
        ),
    )
    db_session.add(row)
    db_session.commit()

    response = client.get("/admin/audit-log?target_search=synthetic-target", headers=super_admin_headers)
    entry = response.json()["items"][0]
    details = entry["details"]
    assert details["new_role"] == "super_admin"
    assert details["nested"]["api_key"] == "[redacted]"
    assert details["nested"]["Authorization"] == "[redacted]"
    assert details["reset_token"] == "[redacted]"
    assert details["password_hash"] == "[redacted]"
    assert details["cookie"] == "[redacted]"
    # No raw secret value ever appears anywhere in the serialized response.
    raw_text = response.text
    assert "sk-live-abc123" not in raw_text
    assert "raw-token-value" not in raw_text
    assert "Bearer xyz" not in raw_text


def test_oversized_details_are_omitted_not_errored(client, db_session, super_admin_headers):
    huge_details = json.dumps({"blob": "x" * 10_000})
    row = PlatformAuditLog(
        actor_user_id=None,
        actor_email="oversized@example.com",
        action="user.platform_role_granted",
        target_user_email="oversized-target@example.com",
        reason="synthetic oversized row",
        details=huge_details,
    )
    db_session.add(row)
    db_session.commit()

    response = client.get("/admin/audit-log?target_search=oversized-target", headers=super_admin_headers)
    assert response.status_code == 200
    entry = response.json()["items"][0]
    assert entry["details"] is None


def test_client_ip_is_masked_not_raw(client, db_session, super_admin_headers):
    target = make_user(db_session, email="ip-masking@example.com")
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    row = db_session.query(PlatformAuditLog).filter_by(target_user_id=target.id).one()
    assert row.client_ip is not None  # a raw value was actually recorded

    response = client.get(f"/admin/audit-log?target_user_id={target.id}", headers=super_admin_headers)
    entry = response.json()["items"][0]
    # Never the exact raw value from the row.
    assert entry["client_ip"] != row.client_ip or entry["client_ip"] is None


def test_every_successful_platform_mutation_writes_exactly_one_audit_row(
    client, db_session, super_admin_headers
):
    org = Organization(name="Sweep Org")
    db_session.add(org)
    db_session.commit()

    target = make_user(db_session, email="sweep-target@example.com", verified=False)
    second_admin = make_user(db_session, email="sweep-second-admin@example.com")
    second_admin.platform_role = "super_admin"
    db_session.commit()

    before = db_session.query(PlatformAuditLog).count()

    calls = [
        ("post", f"/admin/organizations/{org.id}/suspend", {"reason": "test"}, super_admin_headers),
        ("post", f"/admin/organizations/{org.id}/reactivate", {"reason": "test"}, super_admin_headers),
        ("post", f"/admin/users/{target.id}/disable", {"reason": "test"}, super_admin_headers),
        ("post", f"/admin/users/{target.id}/enable", {"reason": "test"}, super_admin_headers),
        ("post", f"/admin/users/{target.id}/verify-email", None, super_admin_headers),
        ("post", f"/admin/users/{target.id}/send-password-reset", None, super_admin_headers),
        (
            "post",
            f"/admin/users/{target.id}/platform-role",
            {"role": "super_admin", "reason": "test"},
            super_admin_headers,
        ),
        (
            "post",
            f"/admin/users/{target.id}/platform-role",
            {"role": None, "reason": "test"},
            _headers(second_admin),
        ),
    ]
    for method, url, body, headers in calls:
        response = getattr(client, method)(url, json=body, headers=headers)
        assert response.status_code == 200, f"{url} failed: {response.text}"

    after = db_session.query(PlatformAuditLog).count()
    assert after - before == len(calls)


def test_failed_or_conflicted_mutations_write_no_audit_row(client, db_session, super_admin_headers):
    target = make_user(db_session, email="conflict-sweep@example.com", verified=True)
    client.post(f"/admin/users/{target.id}/disable", json={"reason": "test"}, headers=super_admin_headers)

    before = db_session.query(PlatformAuditLog).count()

    # Already disabled -> 409, already verified -> 409, blank reason -> 422.
    conflicting_calls = [
        ("post", f"/admin/users/{target.id}/disable", {"reason": "test"}),
        ("post", f"/admin/users/{target.id}/verify-email", None),
        ("post", f"/admin/users/{target.id}/enable", {"reason": "   "}),
    ]
    for method, url, body in conflicting_calls:
        response = getattr(client, method)(url, json=body, headers=super_admin_headers)
        assert response.status_code in (409, 422)

    after = db_session.query(PlatformAuditLog).count()
    assert after == before


def test_organization_role_management_never_writes_platform_audit_log(client, db_session, super_admin_headers):
    """Org-scoped team/role actions (app.services.team) are a completely
    separate concern from platform-level audit events -- confirmed here
    by exercising a role change and a member removal and asserting zero
    new PlatformAuditLog rows, matching app.services.team's structural
    isolation from app.services.platform_audit (no import of it at all)."""
    from app.membership_role import MembershipRole
    from tests.factories import make_member_in_org

    owner = make_org_with_owner(db_session, email="team-audit-owner@example.com")
    member = make_member_in_org(
        db_session, owner.organization, email="team-audit-member@example.com", role=MembershipRole.member
    )

    before = db_session.query(PlatformAuditLog).count()

    role_change = client.patch(
        f"/organizations/{owner.organization.id}/members/{member.membership.id}",
        json={"role": "viewer"},
        headers=owner.auth_headers,
    )
    assert role_change.status_code == 200

    removal = client.post(
        f"/organizations/{owner.organization.id}/members/{member.membership.id}/remove",
        headers=owner.auth_headers,
    )
    assert removal.status_code == 200

    after = db_session.query(PlatformAuditLog).count()
    assert after == before
