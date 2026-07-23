"""Phase 14A -- platform-administered commercial plans: CRUD, activate/
deactivate, make-default, optimistic concurrency, and audit. See
tests/test_entitlements.py for the organization-facing read side."""

import json

from app.models import Plan, PlatformAuditLog
from app.security import create_access_token
from tests.factories import make_user


def _audit_rows(db_session, action: str) -> list[PlatformAuditLog]:
    return db_session.query(PlatformAuditLog).filter_by(action=action).all()


def _current_version(client, super_admin_headers, plan_id: str) -> int:
    return client.get(f"/admin/plans/{plan_id}", headers=super_admin_headers).json()["version"]


def test_list_plans_requires_platform_role(client, db_session):
    user = make_user(db_session, email="not-an-admin@example.com")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    response = client.get("/admin/plans", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "platform_permission_denied"


def test_list_plans_returns_seeded_defaults_in_sort_order(client, super_admin_headers):
    response = client.get("/admin/plans", headers=super_admin_headers)

    assert response.status_code == 200
    items = response.json()["items"]
    codes = [item["code"] for item in items]
    assert codes == ["free", "starter", "pro", "enterprise"]

    free = items[0]
    assert free["is_default"] is True
    assert free["is_active"] is True
    assert free["limits"]["max_users"] == 2
    assert free["limits"]["max_customers"] == 100
    assert free["features"]["custom_branding_enabled"] is False
    assert free["version"] == 1

    enterprise = items[3]
    assert enterprise["limits"]["max_users"] is None
    assert enterprise["features"]["api_access_enabled"] is True


def test_get_plan_404_for_missing_id(client, super_admin_headers):
    response = client.get("/admin/plans/does-not-exist", headers=super_admin_headers)
    assert response.status_code == 404


def test_create_plan_requires_reason_and_valid_code(client, super_admin_headers):
    missing_reason = client.post(
        "/admin/plans",
        json={"code": "custom", "name": "Custom", "max_users": 5},
        headers=super_admin_headers,
    )
    assert missing_reason.status_code == 422

    bad_code = client.post(
        "/admin/plans",
        json={"code": "Not Valid!", "name": "Custom", "reason": "test"},
        headers=super_admin_headers,
    )
    assert bad_code.status_code == 422


def test_create_plan_succeeds_and_records_audit(client, db_session, super_admin_headers, super_admin):
    response = client.post(
        "/admin/plans",
        json={
            "code": "custom",
            "name": "Custom",
            "description": "A custom mid-tier plan",
            "sort_order": 5,
            "max_users": 20,
            "max_customers": 2000,
            "storage_limit_mb": 10240,
            "advanced_reports_enabled": True,
            "reason": "adding a custom plan for a pilot customer",
        },
        headers=super_admin_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "custom"
    assert body["is_active"] is True
    assert body["is_default"] is False
    assert body["limits"]["max_users"] == 20
    assert body["limits"]["max_products"] is None
    assert body["features"]["advanced_reports_enabled"] is True
    assert body["version"] == 1

    rows = _audit_rows(db_session, "platform.plan_created")
    assert len(rows) == 1
    assert rows[0].actor_email == super_admin.email
    assert rows[0].reason == "adding a custom plan for a pilot customer"
    details = json.loads(rows[0].details)
    assert details["code"] == "custom"


def test_create_plan_rejects_duplicate_code(client, super_admin_headers):
    response = client.post(
        "/admin/plans",
        json={"code": "free", "name": "Another Free", "reason": "test"},
        headers=super_admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_code_taken"


def test_create_plan_rejects_negative_limits(client, super_admin_headers):
    response = client.post(
        "/admin/plans",
        json={"code": "bad", "name": "Bad", "max_users": -1, "reason": "test"},
        headers=super_admin_headers,
    )
    assert response.status_code == 422


def test_patch_plan_updates_and_increments_version(client, db_session, super_admin_headers, super_admin):
    plan = db_session.query(Plan).filter_by(code="starter").one()

    response = client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "raising starter user limit", "expected_version": 1, "max_users": 15},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limits"]["max_users"] == 15
    assert body["version"] == 2

    rows = _audit_rows(db_session, "platform.plan_updated")
    assert len(rows) == 1
    details = json.loads(rows[0].details)
    assert details["old_version"] == 1
    assert details["new_version"] == 2
    assert details["max_users"] == {"old": 10, "new": 15}


def test_patch_plan_code_field_is_ignored_immutable(client, db_session, super_admin_headers):
    plan = db_session.query(Plan).filter_by(code="starter").one()

    response = client.patch(
        f"/admin/plans/{plan.id}",
        json={
            "reason": "test",
            "expected_version": 1,
            "code": "renamed",
            "max_users": 15,
        },
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["code"] == "starter"

    db_session.refresh(plan)
    assert plan.code == "starter"


def test_patch_plan_no_op_returns_409_and_no_audit(client, db_session, super_admin_headers):
    plan = db_session.query(Plan).filter_by(code="starter").one()

    response = client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "test", "expected_version": 1, "max_users": plan.max_users},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_changes"
    assert len(_audit_rows(db_session, "platform.plan_updated")) == 0


def test_patch_plan_stale_version_returns_409_conflict_no_audit(client, db_session, super_admin_headers):
    plan = db_session.query(Plan).filter_by(code="starter").one()

    first = client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "first change", "expected_version": 1, "max_users": 12},
        headers=super_admin_headers,
    )
    assert first.status_code == 200

    stale = client.patch(
        f"/admin/plans/{plan.id}",
        json={"reason": "second change with stale version", "expected_version": 1, "max_users": 20},
        headers=super_admin_headers,
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "plan_version_conflict"
    assert stale.json()["detail"]["current_version"] == 2
    assert len(_audit_rows(db_session, "platform.plan_updated")) == 1


def test_deactivate_and_activate_plan(client, db_session, super_admin_headers, super_admin):
    plan = db_session.query(Plan).filter_by(code="starter").one()

    deactivate = client.post(
        f"/admin/plans/{plan.id}/deactivate",
        json={"reason": "retiring starter temporarily", "expected_version": 1},
        headers=super_admin_headers,
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False
    assert deactivate.json()["version"] == 2

    already_inactive = client.post(
        f"/admin/plans/{plan.id}/deactivate",
        json={"reason": "test", "expected_version": 2},
        headers=super_admin_headers,
    )
    assert already_inactive.status_code == 409
    assert already_inactive.json()["detail"]["code"] == "plan_already_inactive"

    activate = client.post(
        f"/admin/plans/{plan.id}/activate",
        json={"reason": "bringing starter back", "expected_version": 2},
        headers=super_admin_headers,
    )
    assert activate.status_code == 200
    assert activate.json()["is_active"] is True
    assert activate.json()["version"] == 3

    activated_rows = _audit_rows(db_session, "platform.plan_activated")
    deactivated_rows = _audit_rows(db_session, "platform.plan_deactivated")
    assert len(activated_rows) == 1
    assert len(deactivated_rows) == 1


def test_cannot_deactivate_the_default_plan(client, db_session, super_admin_headers):
    free = db_session.query(Plan).filter_by(code="free").one()

    response = client.post(
        f"/admin/plans/{free.id}/deactivate",
        json={"reason": "test", "expected_version": 1},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_deactivate_default_plan"


def test_inactive_plan_cannot_be_assigned_to_an_organization(client, db_session, super_admin_headers):
    from tests.factories import make_org_with_owner

    plan = db_session.query(Plan).filter_by(code="starter").one()
    client.post(
        f"/admin/plans/{plan.id}/deactivate",
        json={"reason": "test", "expected_version": 1},
        headers=super_admin_headers,
    )

    owner = make_org_with_owner(db_session, email="assign-inactive@example.com", org_name="Assign Inactive Co")

    response = client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": plan.id, "reason": "trying to assign an inactive plan"},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_inactive"


def test_make_default_clears_old_default_and_sets_new(client, db_session, super_admin_headers, super_admin):
    starter = db_session.query(Plan).filter_by(code="starter").one()

    response = client.post(
        f"/admin/plans/{starter.id}/make-default",
        json={"reason": "switching the default plan to starter", "expected_version": 1},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_default"] is True
    assert body["version"] == 2

    all_plans = client.get("/admin/plans", headers=super_admin_headers).json()["items"]
    defaults = [p for p in all_plans if p["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["code"] == "starter"

    free = next(p for p in all_plans if p["code"] == "free")
    assert free["is_default"] is False

    rows = _audit_rows(db_session, "platform.plan_default_changed")
    assert len(rows) == 1
    details = json.loads(rows[0].details)
    assert details["old_default"]["code"] == "free"
    assert details["new_default"]["code"] == "starter"


def test_make_default_recovers_from_a_pre_existing_double_default(client, db_session, super_admin_headers):
    """Simulates the end-state a genuine race between two concurrent
    make-default calls on two *different* plans could otherwise leave
    behind (see make_default_platform_plan's own docstring): two rows
    marked is_default=True at once, which should never happen but this
    proves the endpoint is self-healing if it ever did, since the clear
    step uses a live "every OTHER row" predicate rather than a specific
    plan id captured before the racing writes."""
    free = db_session.query(Plan).filter_by(code="free").one()
    starter = db_session.query(Plan).filter_by(code="starter").one()
    pro = db_session.query(Plan).filter_by(code="pro").one()
    starter.is_default = True  # simulate the broken double-default state directly
    db_session.commit()
    assert {p.code for p in db_session.query(Plan).filter_by(is_default=True).all()} == {"free", "starter"}

    response = client.post(
        f"/admin/plans/{pro.id}/make-default",
        json={"reason": "recovering from a bad state", "expected_version": pro.version},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    all_plans = client.get("/admin/plans", headers=super_admin_headers).json()["items"]
    defaults = [p for p in all_plans if p["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["code"] == "pro"


def test_make_default_rejects_inactive_plan(client, db_session, super_admin_headers):
    plan = db_session.query(Plan).filter_by(code="starter").one()
    client.post(
        f"/admin/plans/{plan.id}/deactivate",
        json={"reason": "test", "expected_version": 1},
        headers=super_admin_headers,
    )

    response = client.post(
        f"/admin/plans/{plan.id}/make-default",
        json={"reason": "test", "expected_version": 2},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_inactive"


def test_make_default_already_default_returns_409(client, db_session, super_admin_headers):
    free = db_session.query(Plan).filter_by(code="free").one()

    response = client.post(
        f"/admin/plans/{free.id}/make-default",
        json={"reason": "test", "expected_version": 1},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_already_default"


def test_new_organization_receives_the_current_default_plan(client, db_session):
    response = client.post(
        "/auth/register",
        json={
            "email": "plan-default-check@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "Default Plan Co",
        },
    )
    assert response.status_code == 201

    from app.models import Organization

    org = db_session.query(Organization).filter_by(name="Default Plan Co").one()
    assert org.plan_id == "plan_free"


def test_new_organization_follows_a_changed_default_plan(client, db_session, super_admin_headers):
    starter = db_session.query(Plan).filter_by(code="starter").one()
    client.post(
        f"/admin/plans/{starter.id}/make-default",
        json={"reason": "test", "expected_version": 1},
        headers=super_admin_headers,
    )

    response = client.post(
        "/auth/register",
        json={
            "email": "plan-follows-default@example.com",
            "password": "Correct-Horse-1",
            "organization_name": "Follows Default Co",
        },
    )
    assert response.status_code == 201

    from app.models import Organization

    org = db_session.query(Organization).filter_by(name="Follows Default Co").one()
    assert org.plan_id == starter.id


def test_organization_plan_change_requires_reason(client, db_session, super_admin_headers):
    from tests.factories import make_org_with_owner

    owner = make_org_with_owner(db_session, email="plan-change-reason@example.com", org_name="Reason Co")
    starter = db_session.query(Plan).filter_by(code="starter").one()

    response = client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": starter.id},
        headers=super_admin_headers,
    )
    assert response.status_code == 422


def test_organization_plan_change_succeeds_and_audits_old_and_new_plan(
    client, db_session, super_admin_headers, super_admin
):
    from tests.factories import make_org_with_owner

    owner = make_org_with_owner(db_session, email="plan-change@example.com", org_name="Plan Change Co")
    starter = db_session.query(Plan).filter_by(code="starter").one()

    response = client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": starter.id, "reason": "customer upgraded to starter"},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["plan_code"] == "starter"

    rows = _audit_rows(db_session, "organization.plan_changed")
    assert len(rows) == 1
    assert rows[0].reason == "customer upgraded to starter"
    assert rows[0].target_organization_id == owner.organization.id
    details = json.loads(rows[0].details)
    assert details["old_plan"]["code"] == "free"
    assert details["new_plan"]["code"] == "starter"


def test_organization_plan_change_same_plan_returns_409_no_audit(client, db_session, super_admin_headers):
    from tests.factories import make_org_with_owner

    owner = make_org_with_owner(db_session, email="plan-no-op@example.com", org_name="Plan No-Op Co")

    response = client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": "plan_free", "reason": "test"},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_changes"
    assert len(_audit_rows(db_session, "organization.plan_changed")) == 0


def test_organization_plan_change_does_not_alter_member_roles_or_platform_roles(
    client, db_session, super_admin_headers, super_admin
):
    """Assigning a plan is purely a commercial-entitlement change -- it
    must never touch OrganizationMember.role (the org-RBAC axis) or
    User.platform_role (the platform-admin axis), which are both
    entirely independent of what plan an organization is on."""
    from tests.factories import make_org_with_owner

    owner = make_org_with_owner(db_session, email="plan-change-roles@example.com", org_name="Plan Roles Co")
    enterprise = db_session.query(Plan).filter_by(code="enterprise").one()

    from app.models import OrganizationMember

    membership_before = (
        db_session.query(OrganizationMember)
        .filter_by(organization_id=owner.organization.id, user_id=owner.user.id)
        .one()
    )
    assert membership_before.role == "owner"
    assert owner.user.platform_role is None

    response = client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": enterprise.id, "reason": "verifying plan changes don't touch roles"},
        headers=super_admin_headers,
    )
    assert response.status_code == 200

    db_session.refresh(membership_before)
    db_session.refresh(owner.user)
    assert membership_before.role == "owner"
    assert owner.user.platform_role is None
    # The actor's own platform_role is untouched too.
    db_session.refresh(super_admin)
    assert super_admin.platform_role == "super_admin"


def test_organization_plan_change_requires_organizations_manage_permission(client, db_session):
    from tests.factories import make_org_with_owner

    owner = make_org_with_owner(db_session, email="plan-rbac@example.com", org_name="Plan RBAC Co")
    other_user = make_user(db_session, email="not-an-admin-plan@example.com")
    headers = {"Authorization": f"Bearer {create_access_token(other_user.id)}"}

    response = client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": "plan_starter", "reason": "test"},
        headers=headers,
    )
    assert response.status_code == 403
