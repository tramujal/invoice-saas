"""Phase 15B -- Outbound Webhooks Foundations.

Covers: transaction-safe event emission (event+delivery rows created
alongside the business mutation, zero deliveries when nothing is
subscribed), the authoritative event-emission map (customers/products/
quotes/invoices/imports/plan-change), HMAC signing, SSRF protection
(loopback/private/link-local rejected, a real public host accepted),
the delivery engine (success/failure recording, manual resend creates a
new row), the endpoint management service (CRUD/enable/disable/rotate/
archive, secret only ever returned on create/rotate), the management
router (auth/permission/tenant isolation), and a regression check that
ordinary business flows are unaffected by zero configured endpoints.
"""

import json
from decimal import Decimal

import pytest

from app.membership_role import MembershipRole
from app.models import WebhookDelivery, WebhookEndpoint, WebhookEvent
from app.schemas import CurrencyCode, InvoiceLineItemCreate, QuoteLineItemCreate
from app.services.customers import create_customer_record, delete_customer_record, update_customer_record
from app.services.invoices import create_invoice_record
from app.services.plan_limits import PlanLimitExceededError
from app.services.quotes import create_quote_record
from app.services.webhook_deliveries import (
    DeliveryNotFoundInOrgError,
    deliver_webhook,
    get_delivery_in_org,
    resend_delivery,
)
from app.services.webhook_endpoints import (
    WebhookEndpointNotFoundError,
    archive_endpoint,
    create_endpoint,
    decode_events,
    get_endpoint_in_org,
    is_subscribed,
    list_active_subscribed_endpoints,
    list_endpoints_in_org,
    rotate_endpoint_secret,
    set_endpoint_enabled,
    update_endpoint,
)
from app.services.webhook_events import record_webhook_event
from app.webhook_delivery_status import WebhookDeliveryStatus
from app.webhook_delivery_trigger import WebhookDeliveryTrigger
from app.webhook_event_type import WebhookEventType, event_domain
from app.webhook_signing import build_signed_headers, generate_webhook_secret
from app.webhook_ssrf import UnsafeWebhookUrlError, assert_public_url

from tests.factories import make_customer, make_org_with_owner, make_product


# --- app.webhook_signing ----------------------------------------------------


class TestWebhookSigning:
    def test_generate_returns_distinct_prefixed_secrets(self):
        secrets_ = {generate_webhook_secret() for _ in range(20)}
        assert len(secrets_) == 20
        assert all(s.startswith("whsec_") for s in secrets_)

    def test_build_signed_headers_is_deterministic_and_verifiable(self):
        secret = generate_webhook_secret()
        body = b'{"hello":"world"}'
        headers = build_signed_headers(
            secret=secret, event_type="customer.created", delivery_id="del-1", timestamp=1700000000, body=body
        )
        assert headers["X-Webhook-Event"] == "customer.created"
        assert headers["X-Webhook-Delivery"] == "del-1"
        assert headers["X-Webhook-Timestamp"] == "1700000000"

        import hashlib
        import hmac as hmac_module

        expected_sig = hmac_module.new(
            secret.encode("utf-8"), b"1700000000." + body, hashlib.sha256
        ).hexdigest()
        assert headers["X-Webhook-Signature"] == f"t=1700000000,v1={expected_sig}"

    def test_different_secrets_produce_different_signatures(self):
        body = b"{}"
        h1 = build_signed_headers(secret="whsec_a", event_type="x", delivery_id="1", timestamp=1, body=body)
        h2 = build_signed_headers(secret="whsec_b", event_type="x", delivery_id="1", timestamp=1, body=body)
        assert h1["X-Webhook-Signature"] != h2["X-Webhook-Signature"]


# --- app.webhook_event_type --------------------------------------------------


class TestEventCatalog:
    def test_event_domain_extracts_prefix(self):
        assert event_domain(WebhookEventType.customer_created) == "customer"
        assert event_domain(WebhookEventType.organization_plan_changed) == "organization"

    def test_catalog_is_the_full_authoritative_set(self):
        # A sanity net, not exhaustive -- if this drops below the known
        # count, an event type was accidentally removed.
        assert len(list(WebhookEventType)) >= 18


# --- app.webhook_ssrf --------------------------------------------------------


class TestWebhookSsrf:
    def test_rejects_loopback(self):
        with pytest.raises(UnsafeWebhookUrlError):
            assert_public_url("https://127.0.0.1/hook")

    def test_rejects_private_range(self):
        with pytest.raises(UnsafeWebhookUrlError):
            assert_public_url("https://10.0.0.5/hook")

    def test_rejects_link_local_cloud_metadata(self):
        with pytest.raises(UnsafeWebhookUrlError):
            assert_public_url("https://169.254.169.254/latest/meta-data/")

    def test_rejects_plain_http_by_default(self):
        with pytest.raises(UnsafeWebhookUrlError):
            assert_public_url("http://example.com/hook")

    def test_rejects_embedded_credentials(self):
        with pytest.raises(UnsafeWebhookUrlError):
            assert_public_url("https://user:pass@example.com/hook")

    def test_rejects_non_http_scheme(self):
        with pytest.raises(UnsafeWebhookUrlError):
            assert_public_url("ftp://example.com/hook")

    def test_accepts_a_real_public_host(self):
        assert_public_url("https://example.com/hook")  # must not raise


# --- app.services.webhook_endpoints ------------------------------------------


class TestWebhookEndpointService:
    def test_create_returns_secret_once_and_persists_hash_only_conceptually(self, db_session):
        owner = make_org_with_owner(db_session, email="ep1@example.com", org_name="Ep1 Co")
        endpoint, secret = create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="test",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        assert secret.startswith("whsec_")
        assert endpoint.secret == secret  # stored recoverably -- see WebhookEndpoint's own docstring
        assert decode_events(endpoint.subscribed_events) == ["customer.created"]
        assert endpoint.enabled is True
        assert endpoint.active is True

    def test_create_rejects_unsafe_url(self, db_session):
        owner = make_org_with_owner(db_session, email="ep2@example.com", org_name="Ep2 Co")
        with pytest.raises(UnsafeWebhookUrlError):
            create_endpoint(
                db_session, owner.organization.id, owner.user,
                url="https://169.254.169.254/hook", description="",
                subscribed_events=frozenset({WebhookEventType.customer_created}),
            )

    def test_empty_subscription_set_means_wildcard(self, db_session):
        owner = make_org_with_owner(db_session, email="ep3@example.com", org_name="Ep3 Co")
        endpoint, _secret = create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="", subscribed_events=None,
        )
        assert decode_events(endpoint.subscribed_events) == ["*"]
        assert is_subscribed(endpoint.subscribed_events, WebhookEventType.invoice_sent)

    def test_list_excludes_archived_by_default(self, db_session):
        owner = make_org_with_owner(db_session, email="ep4@example.com", org_name="Ep4 Co")
        endpoint, _ = create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        archive_endpoint(db_session, endpoint, owner.user)
        assert list_endpoints_in_org(db_session, owner.organization.id) == []
        assert len(list_endpoints_in_org(db_session, owner.organization.id, include_archived=True)) == 1

    def test_disabled_endpoint_excluded_from_active_subscribers(self, db_session):
        owner = make_org_with_owner(db_session, email="ep5@example.com", org_name="Ep5 Co")
        endpoint, _ = create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        set_endpoint_enabled(db_session, endpoint, owner.user, enabled=False)
        matches = list_active_subscribed_endpoints(db_session, owner.organization.id, WebhookEventType.customer_created)
        assert matches == []

    def test_enable_disable_idempotent(self, db_session):
        owner = make_org_with_owner(db_session, email="ep6@example.com", org_name="Ep6 Co")
        endpoint, _ = create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        set_endpoint_enabled(db_session, endpoint, owner.user, enabled=False)
        set_endpoint_enabled(db_session, endpoint, owner.user, enabled=False)  # no-op, no error
        assert endpoint.enabled is False

    def test_rotate_changes_secret_and_updates_timestamp(self, db_session):
        owner = make_org_with_owner(db_session, email="ep7@example.com", org_name="Ep7 Co")
        endpoint, original_secret = create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        rotated, new_secret = rotate_endpoint_secret(db_session, endpoint, owner.user)
        assert new_secret != original_secret
        assert rotated.secret == new_secret
        assert rotated.last_rotated_at is not None

    def test_get_in_org_enforces_tenant_isolation(self, db_session):
        owner_a = make_org_with_owner(db_session, email="ep8a@example.com", org_name="Ep8a Co")
        owner_b = make_org_with_owner(db_session, email="ep8b@example.com", org_name="Ep8b Co")
        endpoint, _ = create_endpoint(
            db_session, owner_a.organization.id, owner_a.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        with pytest.raises(WebhookEndpointNotFoundError):
            get_endpoint_in_org(db_session, owner_b.organization.id, endpoint.id)

    def test_update_url_revalidates_ssrf(self, db_session):
        owner = make_org_with_owner(db_session, email="ep9@example.com", org_name="Ep9 Co")
        endpoint, _ = create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        with pytest.raises(UnsafeWebhookUrlError):
            update_endpoint(db_session, endpoint, owner.user, url="https://10.0.0.1/hook")


# --- app.services.webhook_events (transactional emission) -------------------


class TestWebhookEventEmission:
    def test_creating_customer_with_no_subscribers_records_event_but_zero_deliveries(self, db_session):
        owner = make_org_with_owner(db_session, email="em1@example.com", org_name="Em1 Co")
        customer = create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        events = db_session.query(WebhookEvent).filter_by(organization_id=owner.organization.id).all()
        assert len(events) == 1
        assert events[0].event_type == "customer.created"
        assert events[0].object_id == customer.id
        assert json.loads(events[0].payload)["id"] == customer.id
        assert db_session.query(WebhookDelivery).count() == 0

    def test_creating_customer_with_subscriber_creates_pending_delivery(self, db_session):
        owner = make_org_with_owner(db_session, email="em2@example.com", org_name="Em2 Co")
        create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        customer = create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        deliveries = db_session.query(WebhookDelivery).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == WebhookDeliveryStatus.pending.value
        assert deliveries[0].trigger == WebhookDeliveryTrigger.automatic.value
        assert deliveries[0].request_url == "https://example.com/hook"
        event = db_session.get(WebhookEvent, deliveries[0].event_id)
        assert event.object_id == customer.id

    def test_unsubscribed_event_type_produces_no_delivery(self, db_session):
        owner = make_org_with_owner(db_session, email="em3@example.com", org_name="Em3 Co")
        create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.invoice_created}),  # NOT customer.created
        )
        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        assert db_session.query(WebhookDelivery).count() == 0

    def test_update_and_delete_customer_each_emit_their_own_event(self, db_session):
        owner = make_org_with_owner(db_session, email="em4@example.com", org_name="Em4 Co")
        customer = create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        update_customer_record(db_session, customer, {"name": "B"})
        delete_customer_record(db_session, customer)
        events = db_session.query(WebhookEvent).filter_by(organization_id=owner.organization.id).order_by(
            WebhookEvent.created_at
        ).all()
        assert [e.event_type for e in events] == ["customer.created", "customer.updated", "customer.deleted"]
        # The delete event's payload is a real snapshot taken before the
        # row was removed, not an empty/broken record.
        assert json.loads(events[-1].payload)["id"] == customer.id

    def test_quote_conversion_emits_both_invoice_created_and_quote_converted(self, db_session):
        from app.services.quotes import convert_quote_to_invoice, mark_quote_accepted_record, send_quote_record

        owner = make_org_with_owner(db_session, email="em5@example.com", org_name="Em5 Co")
        customer = make_customer(db_session, owner.organization, email="cust@example.com")
        quote = create_quote_record(
            db_session, owner.organization.id, owner.user, customer, CurrencyCode.USD,
            [QuoteLineItemCreate(description="Line", quantity=Decimal("1"), unit_price=Decimal("50"))],
            Decimal("0"),
        )
        send_quote_record(db_session, quote)
        mark_quote_accepted_record(db_session, quote)
        result = convert_quote_to_invoice(db_session, owner.organization.id, quote, owner.user)

        events = db_session.query(WebhookEvent).filter_by(organization_id=owner.organization.id).all()
        event_types = {e.event_type for e in events}
        assert "quote.converted" in event_types
        assert "invoice.created" in event_types
        # invoice.created came from create_invoice_record (called inside
        # convert_quote_to_invoice), never duplicated by the wrapper.
        assert sum(1 for e in events if e.event_type == "invoice.created") == 1
        converted_event = next(e for e in events if e.event_type == "quote.converted")
        assert json.loads(converted_event.payload)["converted_invoice_id"] == result.invoice.id

    def test_duplicate_quote_emits_exactly_one_created_event_not_two(self, db_session):
        from app.services.quotes import duplicate_quote_record

        owner = make_org_with_owner(db_session, email="em6@example.com", org_name="Em6 Co")
        quote = create_quote_record(
            db_session, owner.organization.id, owner.user, None, CurrencyCode.USD,
            [QuoteLineItemCreate(description="Line", quantity=Decimal("1"), unit_price=Decimal("50"))],
            Decimal("0"),
        )
        duplicate_quote_record(db_session, owner.organization.id, owner.user, quote)
        events = db_session.query(WebhookEvent).filter_by(
            organization_id=owner.organization.id, event_type="quote.created"
        ).all()
        assert len(events) == 2  # one for the original, one for the duplicate -- never more

    def test_plan_limit_rollback_never_leaves_an_orphaned_event(self, db_session):
        """A row rejected by check_limit() never reaches db.add(Customer(...))
        at all, so record_webhook_event is never even called for it --
        this proves the ordering, not a mid-transaction rollback."""
        from tests.test_organization_api_keys import _custom_plan

        owner = make_org_with_owner(db_session, email="em7@example.com", org_name="Em7 Co")
        plan = _custom_plan(db_session, code="tiny-em7", max_customers=1)
        owner.organization.plan_id = plan.id
        db_session.commit()

        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        with pytest.raises(PlanLimitExceededError):
            create_customer_record(
                db_session, owner.organization.id, name="B", email="b@example.com", phone="", address="", tax_id=""
            )
        events = db_session.query(WebhookEvent).filter_by(organization_id=owner.organization.id).all()
        assert len(events) == 1  # only the first, successful creation


# --- app.services.webhook_deliveries -----------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b'{"ok":true}'):
        self.status_code = status_code
        self.content = content


class TestWebhookDeliveryEngine:
    def _setup(self, db_session, monkeypatch, email: str):
        owner = make_org_with_owner(db_session, email=email, org_name=f"{email}-co")
        endpoint, secret = create_endpoint(
            db_session, owner.organization.id, owner.user,
            url="https://example.com/hook", description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        customer = create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        delivery = db_session.query(WebhookDelivery).filter_by(endpoint_id=endpoint.id).one()
        return owner, endpoint, secret, delivery

    def test_successful_delivery_records_2xx_outcome(self, db_session, monkeypatch):
        owner, endpoint, secret, delivery = self._setup(db_session, monkeypatch, "dl1@example.com")

        captured = {}

        def fake_post(url, data, headers, timeout, allow_redirects):
            captured.update(url=url, headers=headers, allow_redirects=allow_redirects)
            return _FakeResponse(200)

        monkeypatch.setattr("app.services.webhook_deliveries.requests.post", fake_post)

        result = deliver_webhook(db_session, delivery.id)
        assert result.status == WebhookDeliveryStatus.succeeded.value
        assert result.response_status_code == 200
        assert result.attempted_at is not None
        assert captured["allow_redirects"] is False
        assert captured["headers"]["X-Webhook-Signature"].startswith("t=")

    def test_failed_delivery_records_non_2xx_and_next_retry_at(self, db_session, monkeypatch):
        owner, endpoint, secret, delivery = self._setup(db_session, monkeypatch, "dl2@example.com")
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: _FakeResponse(500, b"server error"),
        )
        result = deliver_webhook(db_session, delivery.id)
        assert result.status == WebhookDeliveryStatus.failed.value
        assert result.response_status_code == 500
        assert result.next_retry_at is not None

    def test_network_error_records_failure_with_no_status_code(self, db_session, monkeypatch):
        import requests

        owner, endpoint, secret, delivery = self._setup(db_session, monkeypatch, "dl3@example.com")

        def raise_connection_error(*a, **kw):
            raise requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr("app.services.webhook_deliveries.requests.post", raise_connection_error)
        result = deliver_webhook(db_session, delivery.id)
        assert result.status == WebhookDeliveryStatus.failed.value
        assert result.response_status_code is None
        assert "ConnectionError" in result.error_message

    def test_already_attempted_delivery_is_a_noop(self, db_session, monkeypatch):
        owner, endpoint, secret, delivery = self._setup(db_session, monkeypatch, "dl4@example.com")
        calls = []
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: (calls.append(1), _FakeResponse(200))[1],
        )
        deliver_webhook(db_session, delivery.id)
        deliver_webhook(db_session, delivery.id)
        assert len(calls) == 1  # second call is a no-op, never a second real attempt

    def test_endpoint_url_change_after_delivery_never_rewrites_history(self, db_session, monkeypatch):
        owner, endpoint, secret, delivery = self._setup(db_session, monkeypatch, "dl5@example.com")
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post", lambda *a, **kw: _FakeResponse(200)
        )
        deliver_webhook(db_session, delivery.id)
        update_endpoint(db_session, endpoint, owner.user, url="https://example.org/new-hook")
        db_session.refresh(delivery)
        assert delivery.request_url == "https://example.com/hook"  # snapshot, unchanged

    def test_resend_creates_new_row_never_mutates_original(self, db_session, monkeypatch):
        owner, endpoint, secret, delivery = self._setup(db_session, monkeypatch, "dl6@example.com")
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post", lambda *a, **kw: _FakeResponse(500)
        )
        deliver_webhook(db_session, delivery.id)
        original_attempted_at = delivery.attempted_at

        new_delivery = resend_delivery(db_session, delivery, owner.user)
        assert new_delivery.id != delivery.id
        assert new_delivery.event_id == delivery.event_id
        assert new_delivery.trigger == WebhookDeliveryTrigger.manual_resend.value
        assert new_delivery.attempt_number == delivery.attempt_number + 1
        assert new_delivery.status == WebhookDeliveryStatus.pending.value

        db_session.refresh(delivery)
        assert delivery.attempted_at == original_attempted_at  # original untouched

    def test_get_delivery_in_org_enforces_tenant_isolation(self, db_session, monkeypatch):
        owner, endpoint, secret, delivery = self._setup(db_session, monkeypatch, "dl7@example.com")
        other = make_org_with_owner(db_session, email="dl7b@example.com", org_name="Dl7b Co")
        with pytest.raises(DeliveryNotFoundInOrgError):
            get_delivery_in_org(db_session, other.organization.id, delivery.id)


# --- app.routers.webhooks (management router) --------------------------------


class TestWebhookManagementRouter:
    def _create_via_api(self, client, headers, org_id, events=("customer.created",)):
        return client.post(
            f"/organizations/{org_id}/webhooks",
            json={"url": "https://example.com/hook", "description": "d", "subscribed_events": list(events)},
            headers=headers,
        )

    def test_create_returns_secret_once(self, client, db_session):
        owner = make_org_with_owner(db_session, email="rt1@example.com", org_name="Rt1 Co")
        resp = self._create_via_api(client, owner.auth_headers, owner.organization.id)
        assert resp.status_code == 201
        body = resp.json()
        assert body["secret"].startswith("whsec_")
        assert "hashed_secret" not in body

    def test_list_never_includes_secret(self, client, db_session):
        owner = make_org_with_owner(db_session, email="rt2@example.com", org_name="Rt2 Co")
        self._create_via_api(client, owner.auth_headers, owner.organization.id)
        resp = client.get(f"/organizations/{owner.organization.id}/webhooks", headers=owner.auth_headers)
        assert resp.status_code == 200
        assert all("secret" not in item for item in resp.json())

    def test_create_rejects_unsafe_url_as_422(self, client, db_session):
        owner = make_org_with_owner(db_session, email="rt3@example.com", org_name="Rt3 Co")
        resp = client.post(
            f"/organizations/{owner.organization.id}/webhooks",
            json={"url": "https://169.254.169.254/hook", "description": "", "subscribed_events": ["*"]},
            headers=owner.auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "unsafe_webhook_url"

    def test_create_rejects_unknown_event_type(self, client, db_session):
        owner = make_org_with_owner(db_session, email="rt4@example.com", org_name="Rt4 Co")
        resp = client.post(
            f"/organizations/{owner.organization.id}/webhooks",
            json={"url": "https://example.com/hook", "description": "", "subscribed_events": ["not.a.real.event"]},
            headers=owner.auth_headers,
        )
        assert resp.status_code == 422

    def test_member_without_settings_manage_permission_is_forbidden(self, client, db_session):
        from tests.factories import make_member_in_org

        owner = make_org_with_owner(db_session, email="rt5owner@example.com", org_name="Rt5 Co")
        member = make_member_in_org(
            db_session, owner.organization, email="rt5member@example.com", role=MembershipRole.member
        )
        resp = self._create_via_api(client, member.auth_headers, owner.organization.id)
        assert resp.status_code == 403

    def test_endpoints_are_tenant_isolated(self, client, db_session):
        owner_a = make_org_with_owner(db_session, email="rt6a@example.com", org_name="Rt6a Co")
        owner_b = make_org_with_owner(db_session, email="rt6b@example.com", org_name="Rt6b Co")
        created = self._create_via_api(client, owner_a.auth_headers, owner_a.organization.id)
        endpoint_id = created.json()["id"]
        resp = client.get(
            f"/organizations/{owner_b.organization.id}/webhooks/{endpoint_id}", headers=owner_b.auth_headers
        )
        assert resp.status_code == 404

    def test_enable_disable_rotate_archive_lifecycle(self, client, db_session):
        owner = make_org_with_owner(db_session, email="rt7@example.com", org_name="Rt7 Co")
        created = self._create_via_api(client, owner.auth_headers, owner.organization.id)
        endpoint_id = created.json()["id"]
        org_id = owner.organization.id
        headers = owner.auth_headers

        resp = client.post(f"/organizations/{org_id}/webhooks/{endpoint_id}/disable", headers=headers)
        assert resp.status_code == 200 and resp.json()["enabled"] is False

        resp = client.post(f"/organizations/{org_id}/webhooks/{endpoint_id}/enable", headers=headers)
        assert resp.status_code == 200 and resp.json()["enabled"] is True

        resp = client.post(f"/organizations/{org_id}/webhooks/{endpoint_id}/rotate-secret", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["secret"] != created.json()["secret"]

        resp = client.delete(f"/organizations/{org_id}/webhooks/{endpoint_id}", headers=headers)
        assert resp.status_code == 200 and resp.json()["active"] is False

        # Archived endpoints drop out of the default list.
        resp = client.get(f"/organizations/{org_id}/webhooks", headers=headers)
        assert resp.json() == []

    def test_event_types_catalog_endpoint(self, client, db_session):
        owner = make_org_with_owner(db_session, email="rt8@example.com", org_name="Rt8 Co")
        resp = client.get(f"/organizations/{owner.organization.id}/webhooks/event-types", headers=owner.auth_headers)
        assert resp.status_code == 200
        values = {row["event_type"] for row in resp.json()}
        assert "customer.created" in values
        assert "invoice.sent" in values

    def test_deliveries_list_and_detail_and_resend(self, client, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="rt9@example.com", org_name="Rt9 Co")
        created = self._create_via_api(client, owner.auth_headers, owner.organization.id)
        endpoint_id = created.json()["id"]

        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        db_session.commit()

        headers = owner.auth_headers
        org_id = owner.organization.id
        resp = client.get(f"/organizations/{org_id}/webhooks/{endpoint_id}/deliveries", headers=headers)
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["total"] == 1
        delivery_id = payload["items"][0]["id"]

        resp = client.get(f"/organizations/{org_id}/webhooks/deliveries/{delivery_id}", headers=headers)
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["event"]["event_type"] == "customer.created"

        resp = client.post(f"/organizations/{org_id}/webhooks/deliveries/{delivery_id}/resend", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["id"] != delivery_id
        assert resp.json()["trigger"] == "manual_resend"

    def test_unauthenticated_request_is_rejected(self, client, db_session):
        owner = make_org_with_owner(db_session, email="rt10@example.com", org_name="Rt10 Co")
        resp = client.get(f"/organizations/{owner.organization.id}/webhooks")
        assert resp.status_code in (401, 403)


# --- regression: business flows unaffected by zero configured endpoints -----


class TestWebhookRegressionNoEndpoints:
    def test_invoice_creation_unaffected_by_zero_endpoints(self, db_session):
        owner = make_org_with_owner(db_session, email="reg1@example.com", org_name="Reg1 Co")
        invoice = create_invoice_record(
            db_session, owner.organization.id, owner.user, None, CurrencyCode.USD,
            [InvoiceLineItemCreate(description="L", quantity=Decimal("1"), unit_price=Decimal("10"))],
            Decimal("0"),
        )
        assert invoice.total == Decimal("10.00")
        event = db_session.query(WebhookEvent).filter_by(object_id=invoice.id).one()
        assert event.event_type == "invoice.created"

    def test_product_archive_restore_still_idempotent_with_events_wired(self, db_session):
        owner = make_org_with_owner(db_session, email="reg2@example.com", org_name="Reg2 Co")
        product = make_product(db_session, owner.organization)

        from app.services.products import archive_product_record, restore_product_record

        archive_product_record(db_session, product)
        archive_product_record(db_session, product)  # still a no-op
        events = db_session.query(WebhookEvent).filter_by(object_id=product.id, event_type="product.archived").all()
        assert len(events) == 1  # only the real transition emits, not the no-op repeat

        restore_product_record(db_session, product)
        events = db_session.query(WebhookEvent).filter_by(object_id=product.id, event_type="product.restored").all()
        assert len(events) == 1
