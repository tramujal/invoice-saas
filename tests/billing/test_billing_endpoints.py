"""Tests for the Phase 17A billing HTTP surface: the tenant-facing
GET /organizations/{id}/subscription (app.routers.billing) and the
platform-admin /admin/subscriptions endpoints (app.routers.platform_admin).
Covers permission enforcement, tenant isolation, 404s, and the observable
shape/behavior of each mutation -- the underlying business rules
themselves are covered by tests/billing/test_billing_service.py."""

from datetime import datetime, timedelta, timezone

from app.security import create_access_token
from app.subscription_status import SubscriptionStatus
from tests.factories import make_org_with_owner, make_plan, make_subscription, make_user


# --- GET /organizations/{id}/subscription (tenant-facing) -----------------


def test_get_subscription_requires_org_membership(client, db_session):
    owner = make_org_with_owner(db_session, email="sub-tenant-owner@example.com", org_name="Sub Tenant Co")
    stranger = make_user(db_session, email="sub-tenant-stranger@example.com")
    stranger_headers = {"Authorization": f"Bearer {create_access_token(stranger.id)}"}

    response = client.get(f"/organizations/{owner.organization.id}/subscription", headers=stranger_headers)

    assert response.status_code == 403


def test_get_subscription_returns_the_organizations_own_subscription(client, db_session):
    owner = make_org_with_owner(db_session, email="sub-tenant-owner2@example.com", org_name="Sub Tenant Co 2")

    response = client.get(f"/organizations/{owner.organization.id}/subscription", headers=owner.auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["organization_id"] == owner.organization.id
    assert body["status"] == SubscriptionStatus.active.value
    assert body["billing_period"] == "monthly"
    assert "capabilities" in body
    assert body["plan"]["id"] == owner.organization.plan_id


def test_get_subscription_never_leaks_provider_fields(client, db_session):
    """Provider-independence check (Phase 17A non-goal): the tenant
    response must never surface provider_name/provider_reference."""
    owner = make_org_with_owner(db_session, email="sub-tenant-provider@example.com", org_name="Provider Check Co")

    response = client.get(f"/organizations/{owner.organization.id}/subscription", headers=owner.auth_headers)

    body = response.json()
    assert "provider_name" not in body
    assert "provider_reference" not in body


def test_get_subscription_reflects_trial_state(client, db_session):
    owner = make_org_with_owner(db_session, email="sub-tenant-trial@example.com", org_name="Trial Tenant Co")
    now = datetime.now(timezone.utc)
    make_subscription(
        db_session,
        owner.organization,
        status=SubscriptionStatus.trialing,
        trial_start=now,
        trial_end=now + timedelta(days=14),
    )

    response = client.get(f"/organizations/{owner.organization.id}/subscription", headers=owner.auth_headers)

    body = response.json()
    assert body["status"] == "trialing"
    assert body["trial_end"] is not None


# --- GET /organizations/{id}/billing/plans (Phase 19 plan catalog) ---------


def test_list_public_plans_requires_org_membership(client, db_session):
    owner = make_org_with_owner(db_session, email="plans-owner@example.com", org_name="Plans Co")
    stranger = make_user(db_session, email="plans-stranger@example.com")
    stranger_headers = {"Authorization": f"Bearer {create_access_token(stranger.id)}"}

    response = client.get(f"/organizations/{owner.organization.id}/billing/plans", headers=stranger_headers)

    assert response.status_code == 403


def test_list_public_plans_excludes_inactive_and_non_public_plans(client, db_session):
    owner = make_org_with_owner(db_session, email="plans-owner2@example.com", org_name="Plans Co 2")
    make_plan(db_session, code="plans-catalog-inactive", sort_order=50, is_active=False, public=True)
    make_plan(db_session, code="plans-catalog-private", sort_order=51, is_active=True, public=False)
    visible = make_plan(db_session, code="plans-catalog-visible", sort_order=52, is_active=True, public=True)

    response = client.get(f"/organizations/{owner.organization.id}/billing/plans", headers=owner.auth_headers)

    assert response.status_code == 200
    codes = [plan["code"] for plan in response.json()]
    assert "plans-catalog-inactive" not in codes
    assert "plans-catalog-private" not in codes
    assert visible.code in codes


def test_list_public_plans_is_ordered_by_sort_order(client, db_session):
    owner = make_org_with_owner(db_session, email="plans-owner3@example.com", org_name="Plans Co 3")
    make_plan(db_session, code="plans-catalog-second", sort_order=101, is_active=True, public=True)
    make_plan(db_session, code="plans-catalog-first", sort_order=100, is_active=True, public=True)

    response = client.get(f"/organizations/{owner.organization.id}/billing/plans", headers=owner.auth_headers)

    codes = [plan["code"] for plan in response.json()]
    assert codes.index("plans-catalog-first") < codes.index("plans-catalog-second")


# --- /admin/subscriptions (platform admin) ---------------------------------


def test_admin_list_subscriptions_requires_platform_permission(client, db_session):
    owner = make_org_with_owner(db_session, email="sub-admin-noperm@example.com", org_name="No Perm Co")

    response = client.get("/admin/subscriptions", headers=owner.auth_headers)

    assert response.status_code == 403


def test_admin_list_subscriptions_returns_every_organizations_subscription(client, db_session, super_admin_headers):
    make_org_with_owner(db_session, email="sub-admin-list1@example.com", org_name="List Co 1")
    make_org_with_owner(db_session, email="sub-admin-list2@example.com", org_name="List Co 2")

    response = client.get("/admin/subscriptions", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    names = {item["organization_name"] for item in body["items"]}
    assert "List Co 1" in names
    assert "List Co 2" in names


def test_admin_list_subscriptions_filters_by_status(client, db_session, super_admin_headers):
    active_owner = make_org_with_owner(db_session, email="sub-admin-active@example.com", org_name="Active Filter Co")
    canceled_owner = make_org_with_owner(
        db_session, email="sub-admin-canceled@example.com", org_name="Canceled Filter Co"
    )
    make_subscription(db_session, canceled_owner.organization, status=SubscriptionStatus.canceled)

    response = client.get("/admin/subscriptions?status=canceled", headers=super_admin_headers)

    assert response.status_code == 200
    names = {item["organization_name"] for item in response.json()["items"]}
    assert "Canceled Filter Co" in names
    assert "Active Filter Co" not in names


def test_admin_get_subscription_detail_includes_event_history(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-detail@example.com", org_name="Detail Co")
    sub_id = make_subscription(db_session, owner.organization).id

    response = client.get(f"/admin/subscriptions/{sub_id}", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["organization_name"] == "Detail Co"
    assert isinstance(body["events"], list)


def test_admin_get_subscription_detail_404s_for_missing_id(client, super_admin_headers):
    response = client.get("/admin/subscriptions/does-not-exist", headers=super_admin_headers)
    assert response.status_code == 404


def test_admin_change_plan_upgrades_and_records_audit_log(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-changeplan@example.com", org_name="Change Plan Co")
    low_plan = make_plan(db_session, code="admin-change-low", sort_order=1)
    high_plan = make_plan(db_session, code="admin-change-high", sort_order=9)
    subscription = make_subscription(db_session, owner.organization, plan=low_plan)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/change-plan",
        json={"plan_id": high_plan.id, "reason": "admin upgraded this account"},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["plan"]["id"] == high_plan.id

    audit = client.get("/admin/audit-log?action=subscription.plan_changed", headers=super_admin_headers)
    matching = [
        item
        for item in audit.json()["items"]
        if item["target_organization_id"] == owner.organization.id
    ]
    assert len(matching) == 1
    assert matching[0]["reason"] == "admin upgraded this account"


def test_admin_change_plan_rejects_inactive_plan(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-inactive@example.com", org_name="Inactive Plan Co")
    inactive_plan = make_plan(db_session, code="admin-inactive-plan", sort_order=5, is_active=False)
    subscription = make_subscription(db_session, owner.organization)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/change-plan",
        json={"plan_id": inactive_plan.id, "reason": "should not be allowed"},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_inactive"


def test_admin_change_plan_rejects_reassigning_the_same_plan(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-samesplan@example.com", org_name="Same Plan Co")
    plan = make_plan(db_session, code="admin-same-plan", sort_order=5)
    subscription = make_subscription(db_session, owner.organization, plan=plan)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/change-plan",
        json={"plan_id": plan.id, "reason": "no actual change"},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_changes"


def test_admin_cancel_subscription(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-cancel@example.com", org_name="Cancel Admin Co")
    subscription = make_subscription(db_session, owner.organization, status=SubscriptionStatus.active)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/cancel",
        json={"reason": "customer requested cancellation"},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "canceled"


def test_admin_reactivate_subscription(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-reactivate@example.com", org_name="Reactivate Admin Co")
    subscription = make_subscription(db_session, owner.organization, status=SubscriptionStatus.canceled)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/reactivate",
        json={"reason": "customer came back"},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_admin_reactivate_rejects_a_subscription_that_was_never_canceled(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-badreactivate@example.com", org_name="Bad Reactivate Co")
    subscription = make_subscription(db_session, owner.organization, status=SubscriptionStatus.active)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/reactivate",
        json={"reason": "should fail"},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_cancelable"


def test_admin_resume_subscription(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-resume@example.com", org_name="Resume Admin Co")
    subscription = make_subscription(db_session, owner.organization, status=SubscriptionStatus.paused)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/resume",
        json={"reason": "provider hold lifted"},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_admin_resume_rejects_a_subscription_that_is_not_paused(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-badresume@example.com", org_name="Bad Resume Co")
    subscription = make_subscription(db_session, owner.organization, status=SubscriptionStatus.active)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/resume",
        json={"reason": "should fail"},
        headers=super_admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_paused"


def test_admin_subscription_actions_reject_blank_reason(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="sub-admin-blankreason@example.com", org_name="Blank Reason Co")
    subscription = make_subscription(db_session, owner.organization, status=SubscriptionStatus.active)

    response = client.post(
        f"/admin/subscriptions/{subscription.id}/cancel",
        json={"reason": "   "},
        headers=super_admin_headers,
    )

    assert response.status_code == 422
