"""Phase 14B -- app.services.organization_usage, the single centralized
place that measures how much of each plan-limited resource an
organization is using, plus the two consumers built on top of it:
GET /organizations/{id}/usage (tenant-facing) and the `usage` field
embedded in GET /admin/organizations/{id} (platform-facing). See
tests/test_entitlements.py for the sibling limits-only endpoint this
phase builds on.
"""

import json
from datetime import datetime, timedelta, timezone

from app.assistant_action_status import AssistantActionStatus
from app.membership_status import MembershipStatus
from app.models import AssistantAction, Plan
from app.security import create_access_token
from app.services.organization_usage import (
    count_ai_actions_current_month,
    count_customers,
    count_invoices_current_month,
    count_products,
    count_quotes_current_month,
    count_storage,
    count_users,
    get_usage_snapshot,
)
from tests.factories import (
    make_customer,
    make_invoice,
    make_member_in_org,
    make_org_with_owner,
    make_product,
    make_quote,
    make_user,
)


def _super_admin_headers(db_session):
    admin = make_user(db_session, email="usage-admin@example.com")
    admin.platform_role = "super_admin"
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_assistant_action(db_session, organization, user, *, created_at, status=AssistantActionStatus.proposed):
    action = AssistantAction(
        organization_id=organization.id,
        user_id=user.id,
        action_name="send_payment_reminder",
        input_payload=json.dumps({}),
        summary="test action",
        status=status.value,
        expires_at=created_at + timedelta(minutes=10),
    )
    db_session.add(action)
    db_session.commit()
    # created_at has a server_default of now() -- backdate it explicitly
    # for the monthly-boundary tests, matching this file's own need to
    # simulate "last month" rows without waiting a real month.
    action.created_at = created_at
    db_session.commit()
    db_session.refresh(action)
    return action


class TestCountUsers:
    def test_counts_only_active_memberships(self, db_session):
        owner = make_org_with_owner(db_session, email="users-owner@example.com", org_name="Users Co")
        member = make_member_in_org(db_session, owner.organization, email="users-member@example.com")
        assert count_users(db_session, owner.organization.id) == 2

        member.membership.status = MembershipStatus.removed.value
        db_session.commit()
        assert count_users(db_session, owner.organization.id) == 1

    def test_tenant_isolation(self, db_session):
        org_a = make_org_with_owner(db_session, email="users-a@example.com", org_name="Users A")
        org_b = make_org_with_owner(db_session, email="users-b@example.com", org_name="Users B")
        make_member_in_org(db_session, org_a.organization, email="users-a2@example.com")

        assert count_users(db_session, org_a.organization.id) == 2
        assert count_users(db_session, org_b.organization.id) == 1


class TestCountCustomers:
    def test_zero_and_correct_count(self, db_session):
        owner = make_org_with_owner(db_session, email="cust-owner@example.com", org_name="Cust Co")
        assert count_customers(db_session, owner.organization.id) == 0

        make_customer(db_session, owner.organization, email="c1@example.com")
        make_customer(db_session, owner.organization, email="c2@example.com")
        assert count_customers(db_session, owner.organization.id) == 2

    def test_deleted_customer_stops_counting(self, db_session):
        owner = make_org_with_owner(db_session, email="cust-del@example.com", org_name="Cust Del Co")
        customer = make_customer(db_session, owner.organization, email="del@example.com")
        assert count_customers(db_session, owner.organization.id) == 1

        db_session.delete(customer)
        db_session.commit()
        assert count_customers(db_session, owner.organization.id) == 0


class TestCountProducts:
    def test_archived_products_excluded_and_restored_products_count_again(self, db_session):
        owner = make_org_with_owner(db_session, email="prod-owner@example.com", org_name="Prod Co")
        product = make_product(db_session, owner.organization, name="Widget")
        assert count_products(db_session, owner.organization.id) == 1

        product.active = False
        db_session.commit()
        assert count_products(db_session, owner.organization.id) == 0

        product.active = True
        db_session.commit()
        assert count_products(db_session, owner.organization.id) == 1


class TestCountInvoicesCurrentMonth:
    def test_counts_only_this_calendar_month(self, db_session):
        owner = make_org_with_owner(db_session, email="inv-owner@example.com", org_name="Inv Co")
        now = datetime.now(timezone.utc)
        invoice_this_month = make_invoice(db_session, owner.organization, owner.user)
        assert count_invoices_current_month(db_session, owner.organization.id, now=now) == 1

        # Backdate to unambiguously "last month" regardless of what day
        # of the month the test happens to run on.
        last_month = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        invoice_this_month.created_at = last_month
        db_session.commit()
        assert count_invoices_current_month(db_session, owner.organization.id, now=now) == 0


class TestCountQuotesCurrentMonth:
    def test_counts_this_month_regardless_of_archived_status(self, db_session):
        owner = make_org_with_owner(db_session, email="quote-owner@example.com", org_name="Quote Co")
        now = datetime.now(timezone.utc)
        quote = make_quote(db_session, owner.organization, owner.user)
        assert count_quotes_current_month(db_session, owner.organization.id, now=now) == 1

        quote.active = False
        db_session.commit()
        assert count_quotes_current_month(db_session, owner.organization.id, now=now) == 1

    def test_hard_deleted_draft_quote_stops_counting(self, db_session):
        owner = make_org_with_owner(db_session, email="quote-del@example.com", org_name="Quote Del Co")
        now = datetime.now(timezone.utc)
        quote = make_quote(db_session, owner.organization, owner.user)
        assert count_quotes_current_month(db_session, owner.organization.id, now=now) == 1

        db_session.delete(quote)
        db_session.commit()
        assert count_quotes_current_month(db_session, owner.organization.id, now=now) == 0

    def test_last_month_quote_excluded(self, db_session):
        owner = make_org_with_owner(db_session, email="quote-month@example.com", org_name="Quote Month Co")
        now = datetime.now(timezone.utc)
        quote = make_quote(db_session, owner.organization, owner.user)
        last_month = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        quote.created_at = last_month
        db_session.commit()
        assert count_quotes_current_month(db_session, owner.organization.id, now=now) == 0


class TestCountAiActionsCurrentMonth:
    def test_counts_all_statuses_this_month_only(self, db_session):
        owner = make_org_with_owner(db_session, email="ai-owner@example.com", org_name="AI Co")
        now = datetime.now(timezone.utc)
        _make_assistant_action(db_session, owner.organization, owner.user, created_at=now)
        _make_assistant_action(
            db_session, owner.organization, owner.user, created_at=now, status=AssistantActionStatus.cancelled
        )
        last_month = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        _make_assistant_action(db_session, owner.organization, owner.user, created_at=last_month)

        assert count_ai_actions_current_month(db_session, owner.organization.id, now=now) == 2

    def test_tenant_isolation(self, db_session):
        owner_a = make_org_with_owner(db_session, email="ai-a@example.com", org_name="AI A")
        owner_b = make_org_with_owner(db_session, email="ai-b@example.com", org_name="AI B")
        now = datetime.now(timezone.utc)
        _make_assistant_action(db_session, owner_a.organization, owner_a.user, created_at=now)

        assert count_ai_actions_current_month(db_session, owner_a.organization.id, now=now) == 1
        assert count_ai_actions_current_month(db_session, owner_b.organization.id, now=now) == 0


class TestCountStorage:
    def test_always_zero(self, db_session):
        owner = make_org_with_owner(db_session, email="storage-owner@example.com", org_name="Storage Co")
        assert count_storage(db_session, owner.organization.id) == 0


class TestGetUsageSnapshot:
    def test_free_plan_has_finite_limits_matching_usage(self, db_session):
        owner = make_org_with_owner(db_session, email="snap-free@example.com", org_name="Snap Free Co")
        make_customer(db_session, owner.organization, email="c@example.com")

        snapshot = get_usage_snapshot(db_session, owner.organization.id)

        assert snapshot.users.used == 1
        assert snapshot.users.limit == 2
        assert snapshot.users.unlimited is False
        assert snapshot.customers.used == 1
        assert snapshot.customers.limit == 100
        assert snapshot.storage.used == 0
        assert snapshot.storage.unlimited is False
        assert snapshot.storage.limit == 500

    def test_enterprise_plan_reports_unlimited(self, db_session, client):
        admin_headers = _super_admin_headers(db_session)
        owner = make_org_with_owner(db_session, email="snap-ent@example.com", org_name="Snap Ent Co")
        enterprise = db_session.query(Plan).filter_by(code="enterprise").one()
        response = client.patch(
            f"/admin/organizations/{owner.organization.id}/plan",
            json={"plan_id": enterprise.id, "reason": "moving to enterprise for snapshot test"},
            headers=admin_headers,
        )
        assert response.status_code == 200

        snapshot = get_usage_snapshot(db_session, owner.organization.id)

        assert snapshot.users.unlimited is True
        assert snapshot.users.limit is None
        assert snapshot.storage.unlimited is True

    def test_zero_limit_plan_reports_unavailable_not_unlimited(self, db_session, client):
        admin_headers = _super_admin_headers(db_session)
        owner = make_org_with_owner(db_session, email="snap-zero@example.com", org_name="Snap Zero Co")
        zero_ai_plan = client.post(
            "/admin/plans",
            json={
                "code": "no-ai-usage",
                "name": "No AI Usage",
                "max_ai_actions_per_month": 0,
                "reason": "test plan with an unavailable AI limit",
            },
            headers=admin_headers,
        ).json()
        client.patch(
            f"/admin/organizations/{owner.organization.id}/plan",
            json={"plan_id": zero_ai_plan["id"], "reason": "test"},
            headers=admin_headers,
        )

        snapshot = get_usage_snapshot(db_session, owner.organization.id)

        assert snapshot.ai_actions.limit == 0
        assert snapshot.ai_actions.unlimited is False
        assert snapshot.ai_actions.used == 0


class TestUsageEndpoint:
    def test_requires_org_membership(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-owner@example.com", org_name="Ep Co")
        stranger = make_user(db_session, email="ep-stranger@example.com")
        stranger_headers = {"Authorization": f"Bearer {create_access_token(stranger.id)}"}

        response = client.get(f"/organizations/{owner.organization.id}/usage", headers=stranger_headers)
        assert response.status_code == 403

    def test_returns_used_limit_unlimited_shape(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-shape@example.com", org_name="Ep Shape Co")
        make_customer(db_session, owner.organization, email="c@example.com")

        response = client.get(f"/organizations/{owner.organization.id}/usage", headers=owner.auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["customers"] == {"used": 1, "limit": 100, "unlimited": False}
        assert set(body.keys()) == {
            "users",
            "customers",
            "products",
            "invoices",
            "quotes",
            "ai_actions",
            "storage",
        }

    def test_no_platform_role_required(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-no-role@example.com", org_name="Ep No Role Co")

        response = client.get(f"/organizations/{owner.organization.id}/usage", headers=owner.auth_headers)

        assert response.status_code == 200
        assert owner.user.platform_role is None


class TestAdminOrganizationDetailUsage:
    def test_usage_embedded_in_organization_detail(self, client, db_session):
        admin_headers = _super_admin_headers(db_session)
        owner = make_org_with_owner(db_session, email="admin-usage@example.com", org_name="Admin Usage Co")
        make_customer(db_session, owner.organization, email="c1@example.com")
        make_customer(db_session, owner.organization, email="c2@example.com")

        response = client.get(f"/admin/organizations/{owner.organization.id}", headers=admin_headers)

        assert response.status_code == 200
        usage = response.json()["usage"]
        assert usage["customers"] == {"used": 2, "limit": 100, "unlimited": False}
        assert usage["users"]["used"] == 1
