"""Phase 22 -- Audit Timeline.

Covers: the audit subsystem as another consumer of
app.notifications.service.emit_event (actor threading, correct
event_type/resource_type/resource_id/metadata), app.audit.queries
.list_audit_entries filtering/pagination, and the tenant-facing
GET /organizations/{id}/audit-entries endpoint (permission gating,
tenant isolation, date-range validation, and a public/anonymous action
recording with no actor).
"""

import json

from app.membership_role import MembershipRole
from app.models import PLAN_ID_ENTERPRISE, AuditEntry, Plan
from app.audit.queries import list_audit_entries
from app.quote_status import QuoteStatus
from app.services.customers import create_customer_record, delete_customer_record, update_customer_record
from app.services.quotes import mark_quote_accepted_record
from app.webhook_event_type import WebhookEventType

from tests.factories import (
    make_customer,
    make_member_in_org,
    make_org_with_owner,
    make_quote,
    make_subscription,
)


def _audit_entries(db_session, organization_id):
    return (
        db_session.query(AuditEntry)
        .filter_by(organization_id=organization_id)
        .order_by(AuditEntry.created_at.asc(), AuditEntry.id.asc())
        .all()
    )


class TestEmitEventRecordsAuditEntry:
    def test_records_actor_user_id_from_an_authenticated_action(self, db_session):
        owner = make_org_with_owner(db_session, email="owner-audit1@example.com")
        customer = create_customer_record(
            db_session,
            owner.organization.id,
            name="Acme",
            email="a@example.com",
            phone="",
            address="",
            tax_id="",
            actor_user_id=owner.user.id,
        )

        entries = _audit_entries(db_session, owner.organization.id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.actor_user_id == owner.user.id
        assert entry.event_type == WebhookEventType.customer_created.value
        assert entry.resource_type == "customer"
        assert entry.resource_id == customer.id
        metadata = json.loads(entry.metadata_json)
        assert metadata["id"] == customer.id
        assert metadata["name"] == "Acme"

    def test_records_none_actor_when_none_is_given(self, db_session):
        owner = make_org_with_owner(db_session, email="owner-audit2@example.com")
        create_customer_record(
            db_session,
            owner.organization.id,
            name="Acme",
            email="a@example.com",
            phone="",
            address="",
            tax_id="",
        )

        entries = _audit_entries(db_session, owner.organization.id)
        assert len(entries) == 1
        assert entries[0].actor_user_id is None

    def test_public_quote_accept_records_no_actor(self, db_session):
        """mark_quote_accepted_record's public-endpoint caller passes no
        actor_user_id -- confirms the service layer itself (not just the
        HTTP router) records the honest "no human actor" value."""
        owner = make_org_with_owner(db_session, email="owner-audit3@example.com")
        quote = make_quote(db_session, owner.organization, owner.user)
        quote.status = QuoteStatus.sent.value
        db_session.commit()

        mark_quote_accepted_record(db_session, quote)

        entries = [
            e
            for e in _audit_entries(db_session, owner.organization.id)
            if e.event_type == WebhookEventType.quote_accepted.value
        ]
        assert len(entries) == 1
        assert entries[0].actor_user_id is None
        assert entries[0].resource_type == "quote"
        assert entries[0].resource_id == quote.id

    def test_one_entry_per_emitted_event_not_per_notification_recipient(self, db_session):
        """A single emit_event call creates exactly one AuditEntry row,
        regardless of how many organization members receive a
        Notification/email as part of the same fan-out."""
        owner = make_org_with_owner(db_session, email="owner-audit4@example.com")
        make_member_in_org(db_session, owner.organization, email="member-audit4@example.com")

        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="", phone="", address="", tax_id=""
        )

        entries = _audit_entries(db_session, owner.organization.id)
        assert len(entries) == 1

    def test_update_and_delete_each_record_their_own_entry(self, db_session):
        owner = make_org_with_owner(db_session, email="owner-audit5@example.com")
        customer = create_customer_record(
            db_session,
            owner.organization.id,
            name="Acme",
            email="",
            phone="",
            address="",
            tax_id="",
            actor_user_id=owner.user.id,
        )
        update_customer_record(db_session, customer, {"name": "Acme Inc"}, actor_user_id=owner.user.id)
        delete_customer_record(db_session, customer, actor_user_id=owner.user.id)

        entries = _audit_entries(db_session, owner.organization.id)
        # SQLite's created_at has only second resolution, so three events
        # fired in the same test can tie on timestamp -- assert the set of
        # event types recorded, not a specific insertion-order tiebreak.
        assert {e.event_type for e in entries} == {
            WebhookEventType.customer_created.value,
            WebhookEventType.customer_updated.value,
            WebhookEventType.customer_deleted.value,
        }
        assert len(entries) == 3
        assert all(e.actor_user_id == owner.user.id for e in entries)


class TestListAuditEntries:
    def _seed(self, db_session):
        owner = make_org_with_owner(db_session, email="owner-list@example.com")
        member = make_member_in_org(db_session, owner.organization, email="member-list@example.com")
        c1 = create_customer_record(
            db_session, owner.organization.id, name="One", email="", phone="", address="", tax_id="",
            actor_user_id=owner.user.id,
        )
        c2 = create_customer_record(
            db_session, owner.organization.id, name="Two", email="", phone="", address="", tax_id="",
            actor_user_id=member.user.id,
        )
        update_customer_record(db_session, c1, {"name": "One Updated"}, actor_user_id=owner.user.id)
        return owner, member, c1, c2

    def test_filters_by_event_type(self, db_session):
        owner, _member, c1, _c2 = self._seed(db_session)
        page = list_audit_entries(
            db_session,
            organization_id=owner.organization.id,
            event_type=WebhookEventType.customer_updated.value,
        )
        assert page.total == 1
        assert page.items[0].resource_id == c1.id

    def test_filters_by_actor_user_id(self, db_session):
        owner, member, _c1, c2 = self._seed(db_session)
        page = list_audit_entries(
            db_session, organization_id=owner.organization.id, actor_user_id=member.user.id
        )
        assert page.total == 1
        assert page.items[0].resource_id == c2.id

    def test_filters_by_resource_type_and_id(self, db_session):
        owner, _member, c1, _c2 = self._seed(db_session)
        page = list_audit_entries(
            db_session,
            organization_id=owner.organization.id,
            resource_type="customer",
            resource_id=c1.id,
        )
        assert page.total == 2  # created + updated
        assert {e.event_type for e in page.items} == {
            WebhookEventType.customer_created.value,
            WebhookEventType.customer_updated.value,
        }

    def test_pagination_total_and_slice(self, db_session):
        owner, _member, _c1, _c2 = self._seed(db_session)
        page = list_audit_entries(db_session, organization_id=owner.organization.id, limit=1, offset=0)
        assert page.total == 3
        assert len(page.items) == 1

        full_page = list_audit_entries(db_session, organization_id=owner.organization.id, limit=10, offset=0)
        assert len(full_page.items) == 3
        # The single limit=1 page's row must be the first row of the
        # full, identically-ordered result set -- proves limit/offset are
        # applied consistently, without depending on SQLite's second-level
        # timestamp resolution to pick a specific "newest" event.
        assert page.items[0].id == full_page.items[0].id

    def test_scoped_to_organization(self, db_session):
        owner_a, _member, _c1, _c2 = self._seed(db_session)
        owner_b = make_org_with_owner(db_session, email="owner-list-b@example.com")
        create_customer_record(
            db_session, owner_b.organization.id, name="Other org", email="", phone="", address="", tax_id="",
            actor_user_id=owner_b.user.id,
        )

        page = list_audit_entries(db_session, organization_id=owner_b.organization.id)
        assert page.total == 1
        assert page.items[0].organization_id == owner_b.organization.id


class TestAuditEntriesEndpoint:
    def _four_roles(self, db_session, suffix):
        owner = make_org_with_owner(db_session, email=f"owner-ep{suffix}@example.com")
        org = owner.organization
        org.plan_id = PLAN_ID_ENTERPRISE
        db_session.commit()
        make_subscription(db_session, org, plan=db_session.get(Plan, PLAN_ID_ENTERPRISE))
        admin = make_member_in_org(db_session, org, email=f"admin-ep{suffix}@example.com", role=MembershipRole.admin)
        member = make_member_in_org(db_session, org, email=f"member-ep{suffix}@example.com", role=MembershipRole.member)
        viewer = make_member_in_org(db_session, org, email=f"viewer-ep{suffix}@example.com", role=MembershipRole.viewer)
        return {"owner": owner, "admin": admin, "member": member, "viewer": viewer}

    def test_owner_and_admin_can_list(self, client, db_session):
        roles = self._four_roles(db_session, "1")
        org_id = roles["owner"].organization.id
        create_customer_record(
            db_session, org_id, name="Acme", email="", phone="", address="", tax_id="",
            actor_user_id=roles["owner"].user.id,
        )

        for role in ("owner", "admin"):
            response = client.get(f"/organizations/{org_id}/audit-entries", headers=roles[role].auth_headers)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == 1
            assert body["items"][0]["actor_email"] == roles["owner"].user.email
            assert body["items"][0]["event_type"] == WebhookEventType.customer_created.value

    def test_member_and_viewer_denied(self, client, db_session):
        roles = self._four_roles(db_session, "2")
        org_id = roles["owner"].organization.id

        for role in ("member", "viewer"):
            response = client.get(f"/organizations/{org_id}/audit-entries", headers=roles[role].auth_headers)
            assert response.status_code == 403

    def test_tenant_isolation(self, client, db_session):
        roles_a = self._four_roles(db_session, "3a")
        roles_b = self._four_roles(db_session, "3b")
        create_customer_record(
            db_session, roles_a["owner"].organization.id, name="A", email="", phone="", address="", tax_id="",
            actor_user_id=roles_a["owner"].user.id,
        )

        response = client.get(
            f"/organizations/{roles_b['owner'].organization.id}/audit-entries",
            headers=roles_b["owner"].auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_invalid_date_range_rejected(self, client, db_session):
        roles = self._four_roles(db_session, "4")
        org_id = roles["owner"].organization.id
        response = client.get(
            f"/organizations/{org_id}/audit-entries",
            params={"date_from": "2026-02-01", "date_to": "2026-01-01"},
            headers=roles["owner"].auth_headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_date_range"

    def test_filters_by_query_params(self, client, db_session):
        roles = self._four_roles(db_session, "5")
        org_id = roles["owner"].organization.id
        customer = make_customer(db_session, roles["owner"].organization)
        create_customer_record(
            db_session, org_id, name="Filtered", email="", phone="", address="", tax_id="",
            actor_user_id=roles["admin"].user.id,
        )

        response = client.get(
            f"/organizations/{org_id}/audit-entries",
            params={"actor_user_id": roles["admin"].user.id},
            headers=roles["owner"].auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["actor_user_id"] == roles["admin"].user.id
        # customer fixture above (make_customer) never goes through
        # emit_event, so it must not appear regardless of filtering.
        assert customer.id not in [item["resource_id"] for item in body["items"]]

    def test_public_action_appears_with_no_actor_email(self, client, db_session):
        roles = self._four_roles(db_session, "6")
        org_id = roles["owner"].organization.id
        quote = make_quote(db_session, roles["owner"].organization, roles["owner"].user)
        quote.status = QuoteStatus.sent.value
        db_session.commit()

        accept = client.post(f"/quotes/public/{quote.public_token}/accept")
        assert accept.status_code == 200

        response = client.get(
            f"/organizations/{org_id}/audit-entries",
            params={"event_type": WebhookEventType.quote_accepted.value},
            headers=roles["owner"].auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["actor_user_id"] is None
        assert body["items"][0]["actor_email"] is None
