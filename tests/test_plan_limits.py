"""Phase 14C -- app.services.plan_limits, the single centralized place
that enforces plan limits, plus the enforcement wired into every
resource-creation path. See tests/test_organization_usage.py (Phase 14B)
for the usage-counting tests this phase's limit checks are built on.
"""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.assistant_action_status import AssistantActionStatus
from app.models import AssistantAction, Customer, Plan, PlatformAuditLog, Product
from app.security import create_access_token
from app.services.plan_limits import (
    LimitedResource,
    PlanLimitExceededError,
    UnknownLimitedResourceError,
    check_limit,
    remaining_capacity,
)
from tests.factories import (
    make_customer,
    make_invoice,
    make_org_with_owner,
    make_product,
    make_quote,
    make_user,
)


def _super_admin_headers(db_session):
    admin = make_user(db_session, email="limits-admin@example.com")
    admin.platform_role = "super_admin"
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _custom_plan(db_session, *, code: str, **overrides) -> Plan:
    """A tiny, arbitrary-code plan for boundary testing -- avoids needing
    to actually create 100 rows to reach the Free plan's real limits.
    Defaults everything to None (unlimited) so a test only has to
    override the one limit it cares about."""
    defaults = dict(
        max_users=None,
        max_customers=None,
        max_products=None,
        max_invoices_per_month=None,
        max_quotes_per_month=None,
        max_ai_actions_per_month=None,
        storage_limit_mb=None,
        custom_branding_enabled=False,
        api_access_enabled=False,
        advanced_reports_enabled=False,
    )
    defaults.update(overrides)
    plan = Plan(code=code, name=code.replace("-", " ").title(), is_active=True, is_default=False, **defaults)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _assign_plan(db_session, organization, plan: Plan) -> None:
    organization.plan_id = plan.id
    db_session.commit()


class TestCheckLimitUnknownResource:
    def test_storage_is_not_a_dispatchable_resource(self, db_session):
        """Storage is deliberately absent from the dispatch table (no
        file-storage subsystem exists) -- calling check_limit for it
        must fail closed, not silently allow."""
        owner = make_org_with_owner(db_session, email="unknown-res@example.com", org_name="Unknown Res Co")
        with pytest.raises(UnknownLimitedResourceError):
            check_limit(db_session, owner.organization.id, "storage")  # type: ignore[arg-type]


class TestCheckLimitCustomers:
    def test_below_limit_passes(self, db_session):
        owner = make_org_with_owner(db_session, email="below@example.com", org_name="Below Co")
        plan = _custom_plan(db_session, code="cust-below", max_customers=5)
        _assign_plan(db_session, owner.organization, plan)
        make_customer(db_session, owner.organization, email="c1@example.com")

        check_limit(db_session, owner.organization.id, LimitedResource.customers)  # no raise

    def test_exactly_at_limit_raises(self, db_session):
        owner = make_org_with_owner(db_session, email="atlimit@example.com", org_name="At Limit Co")
        plan = _custom_plan(db_session, code="cust-at-limit", max_customers=1)
        _assign_plan(db_session, owner.organization, plan)
        make_customer(db_session, owner.organization, email="c1@example.com")

        with pytest.raises(PlanLimitExceededError) as excinfo:
            check_limit(db_session, owner.organization.id, LimitedResource.customers)
        assert excinfo.value.used == 1
        assert excinfo.value.limit == 1
        assert excinfo.value.resource == LimitedResource.customers
        assert excinfo.value.plan_code == "cust-at-limit"

    def test_zero_limit_blocks_the_first_creation(self, db_session):
        owner = make_org_with_owner(db_session, email="zero@example.com", org_name="Zero Co")
        plan = _custom_plan(db_session, code="cust-zero", max_customers=0)
        _assign_plan(db_session, owner.organization, plan)

        with pytest.raises(PlanLimitExceededError):
            check_limit(db_session, owner.organization.id, LimitedResource.customers)

    def test_unlimited_never_raises(self, db_session):
        owner = make_org_with_owner(db_session, email="unlimited@example.com", org_name="Unlimited Co")
        plan = _custom_plan(db_session, code="cust-unlimited", max_customers=None)
        _assign_plan(db_session, owner.organization, plan)
        for i in range(5):
            make_customer(db_session, owner.organization, email=f"c{i}@example.com")

        check_limit(db_session, owner.organization.id, LimitedResource.customers)  # no raise

    def test_tenant_isolation(self, db_session):
        owner_a = make_org_with_owner(db_session, email="iso-a@example.com", org_name="Iso A")
        owner_b = make_org_with_owner(db_session, email="iso-b@example.com", org_name="Iso B")
        plan = _custom_plan(db_session, code="cust-iso", max_customers=1)
        _assign_plan(db_session, owner_a.organization, plan)
        _assign_plan(db_session, owner_b.organization, plan)
        make_customer(db_session, owner_a.organization, email="a1@example.com")

        with pytest.raises(PlanLimitExceededError):
            check_limit(db_session, owner_a.organization.id, LimitedResource.customers)
        check_limit(db_session, owner_b.organization.id, LimitedResource.customers)  # org B untouched, no raise


class TestRemainingCapacity:
    def test_unlimited_returns_none(self, db_session):
        owner = make_org_with_owner(db_session, email="remcap-none@example.com", org_name="Remcap None Co")
        plan = _custom_plan(db_session, code="remcap-none", max_products=None)
        _assign_plan(db_session, owner.organization, plan)

        assert remaining_capacity(db_session, owner.organization.id, LimitedResource.products) is None

    def test_returns_slots_left_never_negative(self, db_session):
        owner = make_org_with_owner(db_session, email="remcap@example.com", org_name="Remcap Co")
        plan = _custom_plan(db_session, code="remcap", max_products=3)
        _assign_plan(db_session, owner.organization, plan)
        make_product(db_session, owner.organization, name="P1")
        make_product(db_session, owner.organization, name="P2")

        assert remaining_capacity(db_session, owner.organization.id, LimitedResource.products) == 1

        make_product(db_session, owner.organization, name="P3")
        make_product(db_session, owner.organization, name="P4")  # over limit already, by direct ORM
        assert remaining_capacity(db_session, owner.organization.id, LimitedResource.products) == 0


class TestCustomersEndpoint:
    def test_last_allowed_creation_succeeds_next_fails_with_error_contract(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-cust@example.com", org_name="Ep Cust Co")
        plan = _custom_plan(db_session, code="ep-cust", max_customers=1)
        _assign_plan(db_session, owner.organization, plan)

        first = client.post(
            f"/organizations/{owner.organization.id}/customers",
            json={"name": "First", "email": "first@example.com"},
            headers=owner.auth_headers,
        )
        assert first.status_code == 201

        second = client.post(
            f"/organizations/{owner.organization.id}/customers",
            json={"name": "Second", "email": "second@example.com"},
            headers=owner.auth_headers,
        )
        assert second.status_code == 409
        body = second.json()["detail"]
        assert body["code"] == "plan_limit_reached"
        assert body["resource"] == "customers"
        assert body["used"] == 1
        assert body["limit"] == 1
        assert body["plan"] == {"id": plan.id, "code": "ep-cust", "name": "Ep Cust"}
        assert "message" in body

        assert db_session.query(Customer).filter_by(organization_id=owner.organization.id).count() == 1

    def test_no_audit_row_for_rejected_creation(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-cust-audit@example.com", org_name="Ep Cust Audit Co")
        plan = _custom_plan(db_session, code="ep-cust-audit", max_customers=0)
        _assign_plan(db_session, owner.organization, plan)

        response = client.post(
            f"/organizations/{owner.organization.id}/customers",
            json={"name": "Blocked", "email": "blocked@example.com"},
            headers=owner.auth_headers,
        )
        assert response.status_code == 409
        assert db_session.query(PlatformAuditLog).count() == 0

    def test_concurrent_requests_when_one_slot_remains(self):
        """Genuine two-thread test with independent DB connections (NOT
        the shared, savepoint-nested `db_session`/`client` fixtures used
        elsewhere in this suite, which bind every request in a test to
        one single, non-thread-safe Session) -- this is the one test in
        this file that can actually exercise check_limit's row lock
        across real concurrent transactions. Exactly one of two
        simultaneous requests for the last remaining slot must succeed;
        final usage must never exceed the limit."""
        import os
        import tempfile

        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import Session as RawSession

        from app.models import Base, Organization, Plan
        from app.services.plan_limits import LimitedResource, PlanLimitExceededError, check_limit

        fd, path = tempfile.mkstemp(suffix=".db", prefix="saas_concurrency_")
        os.close(fd)
        try:
            engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

            @event.listens_for(engine, "connect")
            def _disable_pysqlite_autocommit(dbapi_connection, _record):
                dbapi_connection.isolation_level = None

            @event.listens_for(engine, "begin")
            def _emit_begin(conn):
                conn.exec_driver_sql("BEGIN IMMEDIATE")

            Base.metadata.create_all(engine)

            with RawSession(engine) as setup_db:
                plan = Plan(code="race-plan", name="Race Plan", is_active=True, is_default=True, max_customers=1)
                setup_db.add(plan)
                setup_db.flush()
                org = Organization(name="Race Co", plan_id=plan.id)
                setup_db.add(org)
                setup_db.commit()
                org_id = org.id

            barrier = threading.Barrier(2)
            results: list[int] = []
            results_lock = threading.Lock()

            def attempt(name: str) -> None:
                with RawSession(engine) as db:
                    barrier.wait()
                    try:
                        check_limit(db, org_id, LimitedResource.customers)
                        customer = Customer(organization_id=org_id, name=name, email=f"{name}@example.com")
                        db.add(customer)
                        db.commit()
                        with results_lock:
                            results.append(1)
                    except PlanLimitExceededError:
                        db.rollback()
                        with results_lock:
                            results.append(0)

            threads = [threading.Thread(target=attempt, args=(f"racer-{i}",)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            assert sorted(results) == [0, 1], f"expected exactly one success, one rejection; got {results}"

            with RawSession(engine) as verify_db:
                final_count = verify_db.query(Customer).filter_by(organization_id=org_id).count()
            assert final_count == 1
        finally:
            engine.dispose()
            try:
                os.remove(path)
            except OSError:
                pass


class TestProductsEndpoint:
    def test_restore_is_gated_by_the_same_limit_as_create(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-prod-restore@example.com", org_name="Ep Prod Restore Co")
        plan = _custom_plan(db_session, code="ep-prod-restore", max_products=1)
        _assign_plan(db_session, owner.organization, plan)
        archived = make_product(db_session, owner.organization, name="Archived")
        archived.active = False
        db_session.commit()
        make_product(db_session, owner.organization, name="Active")  # fills the one slot

        response = client.post(
            f"/organizations/{owner.organization.id}/products/{archived.id}/restore",
            headers=owner.auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "plan_limit_reached"
        db_session.refresh(archived)
        assert archived.active is False

    def test_import_stops_admitting_rows_once_limit_reached(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-prod-import@example.com", org_name="Ep Prod Import Co")
        plan = _custom_plan(db_session, code="ep-prod-import", max_products=1)
        _assign_plan(db_session, owner.organization, plan)

        csv_content = (
            "name,default_unit_price\n"
            "First,10.00\n"
            "Second,20.00\n"
        )
        response = client.post(
            f"/organizations/{owner.organization.id}/products/import/confirm",
            files={"file": ("products.csv", csv_content, "text/csv")},
            headers=owner.auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["imported_count"] == 1
        assert body["failed_count"] == 1
        failed_row = next(r for r in body["row_results"] if r["status"] == "failed")
        assert failed_row["reason_code"] == "plan_limit_reached"
        assert db_session.query(Product).filter_by(organization_id=owner.organization.id).count() == 1


class TestInvoicesEndpoint:
    def test_monthly_limit_resets_next_month(self, db_session):
        owner = make_org_with_owner(db_session, email="ep-inv-month@example.com", org_name="Ep Inv Month Co")
        plan = _custom_plan(db_session, code="ep-inv-month", max_invoices_per_month=1)
        _assign_plan(db_session, owner.organization, plan)

        invoice = make_invoice(db_session, owner.organization, owner.user)
        with pytest.raises(PlanLimitExceededError):
            check_limit(db_session, owner.organization.id, LimitedResource.invoices)

        now = datetime.now(timezone.utc)
        last_month = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        invoice.created_at = last_month
        db_session.commit()

        check_limit(db_session, owner.organization.id, LimitedResource.invoices)  # no raise -- new month


class TestQuotesEndpoint:
    def test_duplicate_and_convert_are_gated(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-quote-dup@example.com", org_name="Ep Quote Dup Co")
        plan = _custom_plan(db_session, code="ep-quote-dup", max_quotes_per_month=1)
        _assign_plan(db_session, owner.organization, plan)
        quote = make_quote(db_session, owner.organization, owner.user)

        response = client.post(
            f"/organizations/{owner.organization.id}/quotes/{quote.id}/duplicate",
            headers=owner.auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "plan_limit_reached"

    def test_convert_gated_by_invoice_limit_not_quote_limit(self, client, db_session):
        from app.quote_status import QuoteStatus

        owner = make_org_with_owner(db_session, email="ep-quote-convert@example.com", org_name="Ep Quote Convert Co")
        # Unlimited quotes, zero invoices -- proves convert checks the
        # invoice limit, not the quote limit.
        plan = _custom_plan(db_session, code="ep-quote-convert", max_quotes_per_month=None, max_invoices_per_month=0)
        _assign_plan(db_session, owner.organization, plan)
        quote = make_quote(db_session, owner.organization, owner.user)
        quote.status = QuoteStatus.accepted.value
        db_session.commit()

        response = client.post(
            f"/organizations/{owner.organization.id}/quotes/{quote.id}/convert",
            headers=owner.auth_headers,
        )
        assert response.status_code == 409
        body = response.json()["detail"]
        assert body["code"] == "plan_limit_reached"
        assert body["resource"] == "invoices"


class TestAiActionsEndpoint:
    def test_count_ai_actions_gate(self, db_session):
        owner = make_org_with_owner(db_session, email="ep-ai@example.com", org_name="Ep Ai Co")
        plan = _custom_plan(db_session, code="ep-ai", max_ai_actions_per_month=1)
        _assign_plan(db_session, owner.organization, plan)
        db_session.add(
            AssistantAction(
                organization_id=owner.organization.id,
                user_id=owner.user.id,
                action_name="send_payment_reminder",
                input_payload=json.dumps({}),
                summary="test",
                status=AssistantActionStatus.executed.value,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
        )
        db_session.commit()

        with pytest.raises(PlanLimitExceededError) as excinfo:
            check_limit(db_session, owner.organization.id, LimitedResource.ai_actions)
        assert excinfo.value.resource == LimitedResource.ai_actions


class TestUsersEndpoint:
    def test_invitation_creation_blocked_when_at_limit(self, client, db_session):
        owner = make_org_with_owner(db_session, email="ep-users-invite@example.com", org_name="Ep Users Invite Co")
        plan = _custom_plan(db_session, code="ep-users-invite", max_users=1)
        _assign_plan(db_session, owner.organization, plan)

        response = client.post(
            f"/organizations/{owner.organization.id}/invitations",
            json={"email": "invitee@example.com", "role": "member"},
            headers=owner.auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "plan_limit_reached"

    def test_acceptance_blocked_when_limit_reached_between_invite_and_accept(self, client, db_session):
        """The authoritative gate: even if the invite itself was created
        while a slot was open, accepting it can still be correctly
        rejected if the org's usage changed in the meantime."""
        from tests.factories import make_member_in_org

        owner = make_org_with_owner(db_session, email="ep-users-accept@example.com", org_name="Ep Users Accept Co")
        plan = _custom_plan(db_session, code="ep-users-accept", max_users=2)
        _assign_plan(db_session, owner.organization, plan)

        invite_response = client.post(
            f"/organizations/{owner.organization.id}/invitations",
            json={"email": "late-invitee@example.com", "role": "member"},
            headers=owner.auth_headers,
        )
        assert invite_response.status_code == 201

        # Someone else fills the org's remaining seat before this invite
        # is accepted.
        make_member_in_org(db_session, owner.organization, email="filled-seat@example.com")

        invitee = make_user(db_session, email="late-invitee@example.com")
        # The raw invitation token isn't exposed via the API response
        # (only the email link has it) -- accept directly through the
        # service layer instead, matching this test's actual goal (the
        # authoritative check, not the public-token plumbing).
        from app.models import OrganizationInvitation
        from app.services.plan_limits import PlanLimitExceededError
        from app.services.team import accept_invitation_record

        invitation = (
            db_session.query(OrganizationInvitation)
            .filter_by(organization_id=owner.organization.id, email="late-invitee@example.com")
            .one()
        )
        with pytest.raises(PlanLimitExceededError):
            accept_invitation_record(db_session, invitation, invitee)
