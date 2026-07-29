"""Phase 15A -- Organization API Keys + the public /api/v1 REST API.

Covers: key generation/hashing (app.api_keys), permission parsing
(app.api_key_permissions), effective status derivation
(app.api_key_status), the service layer (create/list/rotate/revoke/
touch-last-used), the authentication dependency (missing/malformed/
unknown/wrong-secret/revoked/expired/valid), permission enforcement,
tenant isolation, plan-limit enforcement through the API, usage tracking
through the API, audit-log events, and the browser-facing management
endpoints (create/list/rotate/revoke).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.api_key_permissions import ApiKeyPermission, has_api_key_permission, parse_api_key_permissions
from app.api_key_status import ApiKeyStatus, get_effective_api_key_status
from app.api_keys import InvalidApiKeyFormatError, generate_api_key, parse_api_key, verify_api_key_secret
from app.models import Organization, OrganizationApiKey, OrganizationApiKeyAuditLog, Plan
from app.services.organization_api_keys import (
    create_api_key,
    find_api_key_by_prefix,
    get_api_key_in_org,
    list_api_keys_in_org,
    revoke_api_key,
    rotate_api_key,
    touch_api_key_last_used,
)
from tests.factories import make_customer, make_org_with_owner, make_subscription


def _custom_plan(db_session, *, code: str, **overrides) -> Plan:
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
    plan = Plan(code=code, name=code, is_active=True, is_default=False, **defaults)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


# --- app.api_keys ------------------------------------------------------


class TestApiKeyFormat:
    def test_generate_returns_distinct_prefix_and_verifiable_secret(self):
        full_key, prefix, hashed_secret = generate_api_key()
        assert full_key.startswith(f"sk_{prefix}_")
        assert prefix not in ("",)
        assert hashed_secret != full_key
        assert len(hashed_secret) == 64  # sha256 hex digest

    def test_generated_keys_are_unique(self):
        keys = {generate_api_key()[0] for _ in range(50)}
        assert len(keys) == 50

    def test_parse_roundtrips_a_generated_key(self):
        full_key, prefix, hashed_secret = generate_api_key()
        parsed_prefix, secret = parse_api_key(full_key)
        assert parsed_prefix == prefix
        assert verify_api_key_secret(secret, hashed_secret)

    def test_parse_rejects_malformed_keys(self):
        for bad in ["", "sk_onlyoneseg", "notsk_prefix_secret", "sk__", "sk_prefix_"]:
            with pytest.raises(InvalidApiKeyFormatError):
                parse_api_key(bad)

    def test_verify_rejects_wrong_secret(self):
        full_key, _prefix, hashed_secret = generate_api_key()
        assert not verify_api_key_secret("wrong-secret", hashed_secret)


class TestApiKeyPermissions:
    def test_has_permission_pure_membership(self):
        granted = frozenset({ApiKeyPermission.customers_read})
        assert has_api_key_permission(granted, ApiKeyPermission.customers_read)
        assert not has_api_key_permission(granted, ApiKeyPermission.customers_write)

    def test_parse_fails_closed_on_unknown_values(self):
        parsed = parse_api_key_permissions(["customers.read", "not.a.real.permission", ""])
        assert parsed == frozenset({ApiKeyPermission.customers_read})


class TestApiKeyStatus:
    def test_active_when_neither_revoked_nor_expired(self, db_session):
        owner = make_org_with_owner(db_session, email="status-active@example.com", org_name="Status Active Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        assert get_effective_api_key_status(api_key) == ApiKeyStatus.active

    def test_revoked_takes_priority_over_everything(self, db_session):
        owner = make_org_with_owner(db_session, email="status-revoked@example.com", org_name="Status Revoked Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        revoke_api_key(db_session, api_key, owner.user)
        assert get_effective_api_key_status(api_key) == ApiKeyStatus.revoked

    def test_expired_when_expires_at_in_the_past(self, db_session):
        owner = make_org_with_owner(db_session, email="status-expired@example.com", org_name="Status Expired Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        assert get_effective_api_key_status(api_key) == ApiKeyStatus.expired


# --- app.services.organization_api_keys ---------------------------------


class TestCreateApiKey:
    def test_persists_hash_never_the_plaintext_secret(self, db_session):
        owner = make_org_with_owner(db_session, email="create-hash@example.com", org_name="Create Hash Co")
        api_key, full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="CI key", description="used by CI", permissions=frozenset({ApiKeyPermission.customers_read}),
            expires_at=None,
        )
        assert api_key.hashed_secret != full_key
        assert full_key not in (api_key.hashed_secret, api_key.prefix)
        assert api_key.prefix in full_key

    def test_writes_a_created_audit_row(self, db_session):
        owner = make_org_with_owner(db_session, email="create-audit@example.com", org_name="Create Audit Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        rows = db_session.query(OrganizationApiKeyAuditLog).filter_by(api_key_id=api_key.id).all()
        assert len(rows) == 1
        assert rows[0].action == "api_key.created"
        assert rows[0].actor_user_id == owner.user.id


class TestListAndGetApiKeys:
    def test_list_scoped_to_organization(self, db_session):
        owner_a = make_org_with_owner(db_session, email="list-a@example.com", org_name="List A Co")
        owner_b = make_org_with_owner(db_session, email="list-b@example.com", org_name="List B Co")
        create_api_key(
            db_session, owner_a.organization.id, owner_a.user,
            name="a", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        create_api_key(
            db_session, owner_b.organization.id, owner_b.user,
            name="b", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        assert len(list_api_keys_in_org(db_session, owner_a.organization.id)) == 1
        assert len(list_api_keys_in_org(db_session, owner_b.organization.id)) == 1

    def test_find_by_prefix_returns_regardless_of_status(self, db_session):
        owner = make_org_with_owner(db_session, email="find-prefix@example.com", org_name="Find Prefix Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        revoke_api_key(db_session, api_key, owner.user)
        found = find_api_key_by_prefix(db_session, api_key.prefix)
        assert found is not None
        assert found.id == api_key.id


class TestRevokeApiKey:
    def test_idempotent(self, db_session):
        owner = make_org_with_owner(db_session, email="revoke-idem@example.com", org_name="Revoke Idem Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        first = revoke_api_key(db_session, api_key, owner.user)
        first_revoked_at = first.revoked_at
        second = revoke_api_key(db_session, api_key, owner.user)
        assert second.revoked_at == first_revoked_at

    def test_writes_exactly_one_revoked_audit_row_even_when_called_twice(self, db_session):
        owner = make_org_with_owner(db_session, email="revoke-audit@example.com", org_name="Revoke Audit Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        revoke_api_key(db_session, api_key, owner.user)
        revoke_api_key(db_session, api_key, owner.user)
        rows = (
            db_session.query(OrganizationApiKeyAuditLog)
            .filter_by(api_key_id=api_key.id, action="api_key.revoked")
            .all()
        )
        assert len(rows) == 1


class TestRotateApiKey:
    def test_revokes_old_and_creates_new_with_same_permissions(self, db_session):
        owner = make_org_with_owner(db_session, email="rotate@example.com", org_name="Rotate Co")
        old_key, old_full = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="Integration", description="desc", permissions=frozenset({ApiKeyPermission.invoices_read}),
            expires_at=None,
        )
        new_key, new_full = rotate_api_key(db_session, old_key, owner.user)

        db_session.refresh(old_key)
        assert old_key.revoked_at is not None
        assert new_key.id != old_key.id
        assert new_key.name == "Integration"
        assert json.loads(new_key.permissions) == json.loads(old_key.permissions)
        assert new_full != old_full
        assert new_key.prefix != old_key.prefix

    def test_old_key_never_mutated_in_place(self, db_session):
        owner = make_org_with_owner(db_session, email="rotate-history@example.com", org_name="Rotate History Co")
        old_key, _old_full = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        original_prefix = old_key.prefix
        original_hash = old_key.hashed_secret
        rotate_api_key(db_session, old_key, owner.user)
        db_session.refresh(old_key)
        assert old_key.prefix == original_prefix
        assert old_key.hashed_secret == original_hash


class TestTouchLastUsed:
    def test_sets_last_used_on_first_touch(self, db_session):
        owner = make_org_with_owner(db_session, email="touch-first@example.com", org_name="Touch First Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        assert api_key.last_used_at is None
        touch_api_key_last_used(db_session, api_key, "1.2.3.4")
        assert api_key.last_used_at is not None
        assert api_key.last_used_ip == "1.2.3.4"

    def test_throttled_within_interval(self, db_session):
        owner = make_org_with_owner(db_session, email="touch-throttle@example.com", org_name="Touch Throttle Co")
        api_key, _full_key = create_api_key(
            db_session, owner.organization.id, owner.user,
            name="k", description="", permissions=frozenset({ApiKeyPermission.customers_read}), expires_at=None,
        )
        touch_api_key_last_used(db_session, api_key, "1.1.1.1")
        first_touch = api_key.last_used_at
        touch_api_key_last_used(db_session, api_key, "2.2.2.2")
        assert api_key.last_used_at == first_touch
        assert api_key.last_used_ip == "1.1.1.1"  # not overwritten by the throttled call


# --- HTTP-level: authentication dependency -------------------------------


def _create_key_via_api(client, owner, permissions: list[str], expires_at: str | None = None) -> str:
    response = client.post(
        f"/organizations/{owner.organization.id}/api-keys",
        json={"name": "Test key", "description": "", "permissions": permissions, "expires_at": expires_at},
        headers=owner.auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["api_key"]


class TestApiKeyAuthentication:
    def test_missing_authorization_header_rejected(self, client):
        response = client.get("/api/v1/customers")
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "invalid_api_key"

    def test_malformed_bearer_scheme_rejected(self, client):
        response = client.get("/api/v1/customers", headers={"Authorization": "Basic abc123"})
        assert response.status_code == 401

    def test_malformed_key_format_rejected(self, client):
        response = client.get("/api/v1/customers", headers={"Authorization": "Bearer not-a-real-key"})
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "invalid_api_key"

    def test_unknown_prefix_rejected(self, client):
        response = client.get(
            "/api/v1/customers", headers={"Authorization": f"Bearer sk_{uuid.uuid4().hex[:12]}_{uuid.uuid4().hex}"}
        )
        assert response.status_code == 401

    def test_wrong_secret_for_known_prefix_rejected(self, client, db_session):
        owner = make_org_with_owner(db_session, email="wrong-secret@example.com", org_name="Wrong Secret Co")
        full_key = _create_key_via_api(client, owner, ["customers.read"])
        prefix = full_key.split("_")[1]
        response = client.get(
            "/api/v1/customers", headers={"Authorization": f"Bearer sk_{prefix}_wrongsecretvalue"}
        )
        assert response.status_code == 401

    def test_valid_key_with_correct_permission_succeeds(self, client, db_session):
        owner = make_org_with_owner(db_session, email="valid-key@example.com", org_name="Valid Key Co")
        full_key = _create_key_via_api(client, owner, ["customers.read"])
        response = client.get("/api/v1/customers", headers={"Authorization": f"Bearer {full_key}"})
        assert response.status_code == 200

    def test_valid_key_missing_required_permission_403s(self, client, db_session):
        owner = make_org_with_owner(db_session, email="missing-perm@example.com", org_name="Missing Perm Co")
        full_key = _create_key_via_api(client, owner, ["customers.read"])
        response = client.post(
            "/api/v1/customers",
            json={"name": "New Co", "email": "new@example.com"},
            headers={"Authorization": f"Bearer {full_key}"},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "api_key_permission_denied"

    def test_revoked_key_rejected(self, client, db_session):
        owner = make_org_with_owner(db_session, email="revoked-key@example.com", org_name="Revoked Key Co")
        create_response = client.post(
            f"/organizations/{owner.organization.id}/api-keys",
            json={"name": "k", "description": "", "permissions": ["customers.read"]},
            headers=owner.auth_headers,
        )
        full_key = create_response.json()["api_key"]
        key_id = create_response.json()["id"]
        client.post(f"/organizations/{owner.organization.id}/api-keys/{key_id}/revoke", headers=owner.auth_headers)

        response = client.get("/api/v1/customers", headers={"Authorization": f"Bearer {full_key}"})
        assert response.status_code == 401
        audit_rows = (
            db_session.query(OrganizationApiKeyAuditLog).filter_by(api_key_id=key_id, action="api_key.revoked_key_used").all()
        )
        assert len(audit_rows) == 1

    def test_expired_key_rejected(self, client, db_session):
        owner = make_org_with_owner(db_session, email="expired-key@example.com", org_name="Expired Key Co")
        full_key = _create_key_via_api(
            client, owner, ["customers.read"],
            expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        )
        response = client.get("/api/v1/customers", headers={"Authorization": f"Bearer {full_key}"})
        assert response.status_code == 401


# --- HTTP-level: tenant isolation, plan enforcement, usage tracking ------


class TestPublicApiTenantIsolation:
    def test_key_can_only_see_its_own_organization(self, client, db_session):
        owner_a = make_org_with_owner(db_session, email="iso-a@example.com", org_name="Iso A Co")
        owner_b = make_org_with_owner(db_session, email="iso-b@example.com", org_name="Iso B Co")
        make_customer(db_session, owner_a.organization, email="a-customer@example.com")
        make_customer(db_session, owner_b.organization, email="b-customer@example.com")

        full_key_a = _create_key_via_api(client, owner_a, ["customers.read"])
        response = client.get("/api/v1/customers", headers={"Authorization": f"Bearer {full_key_a}"})
        assert response.status_code == 200
        emails = {c["email"] for c in response.json()}
        assert emails == {"a-customer@example.com"}

    def test_key_cannot_fetch_another_orgs_customer_by_id(self, client, db_session):
        owner_a = make_org_with_owner(db_session, email="iso-get-a@example.com", org_name="Iso Get A Co")
        owner_b = make_org_with_owner(db_session, email="iso-get-b@example.com", org_name="Iso Get B Co")
        other_customer = make_customer(db_session, owner_b.organization, email="other@example.com")

        full_key_a = _create_key_via_api(client, owner_a, ["customers.read"])
        response = client.get(
            f"/api/v1/customers/{other_customer.id}", headers={"Authorization": f"Bearer {full_key_a}"}
        )
        assert response.status_code == 404


class TestPublicApiPlanEnforcement:
    def test_plan_limit_reached_through_the_api(self, client, db_session):
        owner = make_org_with_owner(db_session, email="api-plan-limit@example.com", org_name="Api Plan Limit Co")
        plan = _custom_plan(db_session, code="api-limit-1cust", max_customers=1)
        owner.organization.plan_id = plan.id
        db_session.commit()
        make_subscription(db_session, owner.organization, plan=plan)

        full_key = _create_key_via_api(client, owner, ["customers.read", "customers.write"])
        headers = {"Authorization": f"Bearer {full_key}"}

        first = client.post("/api/v1/customers", json={"name": "One", "email": "one@example.com"}, headers=headers)
        assert first.status_code == 201

        second = client.post("/api/v1/customers", json={"name": "Two", "email": "two@example.com"}, headers=headers)
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "plan_limit_reached"


class TestPublicApiUsageTracking:
    def test_customer_created_via_api_shows_up_in_usage(self, client, db_session):
        owner = make_org_with_owner(db_session, email="api-usage@example.com", org_name="Api Usage Co")
        full_key = _create_key_via_api(client, owner, ["customers.read", "customers.write"])
        client.post(
            "/api/v1/customers",
            json={"name": "Via API", "email": "via-api@example.com"},
            headers={"Authorization": f"Bearer {full_key}"},
        )

        usage = client.get(f"/organizations/{owner.organization.id}/usage", headers=owner.auth_headers)
        assert usage.status_code == 200
        assert usage.json()["customers"]["used"] == 1


# --- Browser-facing management endpoints ---------------------------------


class TestApiKeyManagementEndpoints:
    def test_non_admin_member_cannot_manage_keys(self, client, db_session):
        from tests.factories import make_member_in_org
        from app.membership_role import MembershipRole

        owner = make_org_with_owner(db_session, email="mgmt-owner@example.com", org_name="Mgmt Owner Co")
        member = make_member_in_org(
            db_session, owner.organization, email="mgmt-member@example.com", role=MembershipRole.member
        )
        response = client.get(f"/organizations/{owner.organization.id}/api-keys", headers=member.auth_headers)
        assert response.status_code == 403

    def test_create_returns_secret_exactly_once_list_never_does(self, client, db_session):
        owner = make_org_with_owner(db_session, email="mgmt-secret@example.com", org_name="Mgmt Secret Co")
        create_response = client.post(
            f"/organizations/{owner.organization.id}/api-keys",
            json={"name": "k", "description": "", "permissions": ["customers.read"]},
            headers=owner.auth_headers,
        )
        assert "api_key" in create_response.json()

        list_response = client.get(f"/organizations/{owner.organization.id}/api-keys", headers=owner.auth_headers)
        assert list_response.status_code == 200
        for row in list_response.json():
            assert "api_key" not in row

    def test_rotate_via_management_endpoint_invalidates_old_key(self, client, db_session):
        owner = make_org_with_owner(db_session, email="mgmt-rotate@example.com", org_name="Mgmt Rotate Co")
        create_response = client.post(
            f"/organizations/{owner.organization.id}/api-keys",
            json={"name": "k", "description": "", "permissions": ["customers.read"]},
            headers=owner.auth_headers,
        )
        key_id = create_response.json()["id"]
        old_full_key = create_response.json()["api_key"]

        rotate_response = client.post(
            f"/organizations/{owner.organization.id}/api-keys/{key_id}/rotate", headers=owner.auth_headers
        )
        assert rotate_response.status_code == 200
        new_full_key = rotate_response.json()["api_key"]
        assert new_full_key != old_full_key

        old_attempt = client.get("/api/v1/customers", headers={"Authorization": f"Bearer {old_full_key}"})
        assert old_attempt.status_code == 401

        new_attempt = client.get("/api/v1/customers", headers={"Authorization": f"Bearer {new_full_key}"})
        assert new_attempt.status_code == 200
