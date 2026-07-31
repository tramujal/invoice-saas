"""Phase 20 -- Event-Driven Notification System.

Covers: app.notifications.service.emit_event fanning one domain event out
to all three channels (webhook, in-app Notification, notification.email
BackgroundJob), email-preference opt-out, unverified-recipient skipping,
the notification.email job handler's success/retry/permanent-failure
paths, and the tenant-facing notification/preference API (pagination,
unread filtering, mark-read, mark-all-read, tenant isolation, and
default-true preference semantics).
"""

from fastapi import HTTPException

from app.job_type import JobType
from app.jobs.handlers.notification import NotificationEmailPayload, handle_notification_email
from app.jobs.registry import JobOutcome
from app.models import BackgroundJob, Notification, NotificationPreference
from app.notifications.copy import render_notification_copy
from app.notifications.service import emit_event, is_email_enabled, set_email_enabled
from app.services.customers import create_customer_record
from app.services.webhook_endpoints import create_endpoint
from app.webhook_event_type import WebhookEventType

from tests.factories import make_member_in_org, make_org_with_owner, make_user


class TestEmitEventFanOut:
    def test_creates_one_notification_per_active_member(self, db_session):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        member = make_member_in_org(db_session, owner.organization, email="member@example.com")

        customer = create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )

        notifications = (
            db_session.query(Notification).filter_by(organization_id=owner.organization.id).all()
        )
        recipient_ids = {n.user_id for n in notifications}
        assert recipient_ids == {owner.user.id, member.user.id}
        for n in notifications:
            assert n.event_type == WebhookEventType.customer_created.value
            assert n.title == "Customer created"
            assert "Acme" in n.body
            assert n.object_type == "customer"
            assert n.object_id == customer.id
            assert n.read_at is None

    def test_enqueues_a_notification_email_job_per_recipient(self, db_session):
        import json

        owner = make_org_with_owner(db_session, email="owner@example.com")
        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )

        jobs = db_session.query(BackgroundJob).filter_by(job_type=JobType.notification_email.value).all()
        assert len(jobs) == 1
        notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()
        assert json.loads(jobs[0].payload)["notification_id"] == notification.id

    def test_skips_email_job_for_a_member_who_opted_out(self, db_session):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        member = make_member_in_org(db_session, owner.organization, email="member@example.com")
        set_email_enabled(
            db_session, user_id=member.user.id, organization_id=owner.organization.id, enabled=False
        )
        db_session.commit()

        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )

        jobs = db_session.query(BackgroundJob).filter_by(job_type=JobType.notification_email.value).all()
        assert len(jobs) == 1  # only the owner, not the opted-out member

        # Both members still get their in-app Notification row -- opting
        # out of email never touches the in-app channel.
        notifications = db_session.query(Notification).filter_by(organization_id=owner.organization.id).all()
        assert {n.user_id for n in notifications} == {owner.user.id, member.user.id}

    def test_skips_email_job_for_an_unverified_recipient(self, db_session):
        from app.models import User

        owner = make_org_with_owner(db_session, email="owner@example.com")
        make_member_in_org(db_session, owner.organization, email="unverified@example.com")
        user = db_session.query(User).filter_by(email="unverified@example.com").one()
        user.email_verified_at = None
        db_session.commit()

        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )

        jobs = db_session.query(BackgroundJob).filter_by(job_type=JobType.notification_email.value).all()
        assert len(jobs) == 1  # only the (verified) owner

    def test_still_records_the_webhook_event_and_deliveries_unchanged(self, db_session):
        from tests.factories import make_org_with_owner_on_plan

        owner = make_org_with_owner_on_plan(
            db_session, email="owner@example.com", max_webhooks=None, background_jobs_enabled=True
        )
        create_endpoint(
            db_session,
            owner.organization.id,
            owner.user,
            url="https://example.com/hook",
            description="",
            subscribed_events=frozenset({WebhookEventType.customer_created}),
        )
        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )

        webhook_jobs = db_session.query(BackgroundJob).filter_by(job_type=JobType.webhook_deliver.value).all()
        assert len(webhook_jobs) == 1

    def test_no_members_means_no_notifications_and_no_email_jobs(self, db_session):
        """Defensive: emit_event should never crash on an org with zero
        active members (shouldn't happen in practice -- every org keeps
        at least one owner -- but the function must not assume it)."""
        owner = make_org_with_owner(db_session, email="owner@example.com")
        from app.membership_status import MembershipStatus

        owner.membership.status = MembershipStatus.removed.value
        db_session.commit()

        emit_event(
            db_session,
            organization_id=owner.organization.id,
            event_type=WebhookEventType.customer_created,
            object_type="customer",
            object_id="does-not-matter",
            payload={"name": "X"},
        )
        db_session.commit()

        assert db_session.query(Notification).count() == 0
        assert db_session.query(BackgroundJob).filter_by(job_type=JobType.notification_email.value).count() == 0

    def test_email_eligibility_lookups_do_not_scale_with_member_count(self, db_session):
        """Phase P2.2 (H3): before this fix, the per-recipient loop called
        is_email_enabled() (1 query against notification_preferences) and
        db.get(User, ...) (1 query against users) for EVERY active
        member -- 2N queries against those two tables for N members, on
        top of everything else emit_event legitimately does once per
        recipient (one BackgroundJob row + its own idempotency-key check
        per eligible email -- untouched by this fix, since that's real
        per-job work, not a redundant lookup). Counting only statements
        against notification_preferences/users specifically (rather than
        every query emit_event issues) isolates exactly the piece this
        finding is about."""
        from contextlib import contextmanager

        from sqlalchemy import event

        from app.database import engine as app_engine

        @contextmanager
        def _count_matching_statements(*substrings: str):
            count = 0

            def _on_execute(_conn, _cursor, statement, *_rest):
                nonlocal count
                if any(substring in statement for substring in substrings):
                    count += 1

            event.listen(app_engine, "before_cursor_execute", _on_execute)
            try:
                yield lambda: count
            finally:
                event.remove(app_engine, "before_cursor_execute", _on_execute)

        def _emit_for_member_count(member_count: int) -> int:
            owner = make_org_with_owner(db_session, email=f"qc-owner-{member_count}@example.com")
            members = [
                make_member_in_org(db_session, owner.organization, email=f"qc-member-{member_count}-{i}@example.com")
                for i in range(member_count)
            ]
            # A couple of realistic wrinkles so the batched lookups still
            # have to make the same per-recipient decision, not just skip
            # work entirely.
            if members:
                set_email_enabled(
                    db_session, user_id=members[0].user.id, organization_id=owner.organization.id, enabled=False
                )
                members[-1].user.email_verified_at = None
            db_session.commit()

            with _count_matching_statements("FROM notification_preferences", "FROM users") as get_count:
                emit_event(
                    db_session,
                    organization_id=owner.organization.id,
                    event_type=WebhookEventType.customer_created,
                    object_type="customer",
                    object_id="does-not-matter",
                    payload={"name": "Query Count Co"},
                )
            db_session.commit()
            return get_count()

        small_count = _emit_for_member_count(3)
        large_count = _emit_for_member_count(20)

        # Exactly one batched SELECT against each table, regardless of
        # whether there are 4 total active members (owner + 3) or 21
        # (owner + 20) -- if this ever regresses back to a per-member
        # query, these two numbers would diverge instead of both being 2.
        assert small_count == 2, small_count
        assert large_count == 2, large_count


class TestEmailPreference:
    def test_defaults_to_enabled_when_no_row_exists(self, db_session):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        assert is_email_enabled(db_session, user_id=owner.user.id, organization_id=owner.organization.id) is True

    def test_set_email_enabled_creates_a_row_lazily(self, db_session):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        assert db_session.query(NotificationPreference).count() == 0

        set_email_enabled(db_session, user_id=owner.user.id, organization_id=owner.organization.id, enabled=False)
        db_session.commit()

        assert db_session.query(NotificationPreference).count() == 1
        assert is_email_enabled(db_session, user_id=owner.user.id, organization_id=owner.organization.id) is False

    def test_set_email_enabled_updates_an_existing_row_in_place(self, db_session):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        set_email_enabled(db_session, user_id=owner.user.id, organization_id=owner.organization.id, enabled=False)
        db_session.commit()
        set_email_enabled(db_session, user_id=owner.user.id, organization_id=owner.organization.id, enabled=True)
        db_session.commit()

        assert db_session.query(NotificationPreference).count() == 1
        assert is_email_enabled(db_session, user_id=owner.user.id, organization_id=owner.organization.id) is True


class TestNotificationCopy:
    def test_falls_back_gracefully_for_missing_payload_fields(self):
        title, body = render_notification_copy(WebhookEventType.invoice_sent, {})
        assert title == "Invoice sent"
        assert "An invoice" in body
        assert "the customer" in body

    def test_unmapped_event_type_never_raises(self):
        # Every current member IS mapped, but the fallback path itself
        # (a hypothetical future event type) must still produce a usable
        # tuple, not raise.
        class _Fake:
            value = "future.event"

        title, body = render_notification_copy(_Fake(), {})  # type: ignore[arg-type]
        assert title == "future.event"
        assert body


class TestNotificationEmailJobHandler:
    def _enqueue_and_get_job(self, db_session, owner):
        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )
        return db_session.query(BackgroundJob).filter_by(job_type=JobType.notification_email.value).one()

    def test_success_path_sends_via_the_configured_sender(self, db_session, fake_email_sender):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        job = self._enqueue_and_get_job(db_session, owner)
        notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()

        result = handle_notification_email(
            db_session, job, NotificationEmailPayload(notification_id=notification.id)
        )

        assert result.outcome == JobOutcome.succeeded
        assert len(fake_email_sender.sent) == 1
        sent = fake_email_sender.sent[0]
        assert sent.to == owner.user.email
        assert sent.subject == notification.title
        assert sent.text_body == notification.body

    def test_missing_notification_row_is_permanently_failed(self, db_session):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        job = self._enqueue_and_get_job(db_session, owner)

        result = handle_notification_email(
            db_session, job, NotificationEmailPayload(notification_id="does-not-exist")
        )

        assert result.outcome == JobOutcome.permanently_failed
        assert result.error_code == "notification_missing"

    def test_unverified_recipient_at_run_time_is_skipped_not_failed(self, db_session):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        job = self._enqueue_and_get_job(db_session, owner)
        notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()

        owner.user.email_verified_at = None
        db_session.commit()

        result = handle_notification_email(
            db_session, job, NotificationEmailPayload(notification_id=notification.id)
        )

        assert result.outcome == JobOutcome.succeeded
        assert result.result_summary == "skipped_unverified_or_missing_user"

    def test_provider_send_failure_is_retried(self, db_session, fake_email_sender):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        job = self._enqueue_and_get_job(db_session, owner)
        notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()
        fake_email_sender.fail_next_n = 1

        result = handle_notification_email(
            db_session, job, NotificationEmailPayload(notification_id=notification.id)
        )

        assert result.outcome == JobOutcome.retry

    def test_email_not_configured_is_permanently_failed_not_retried(self, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        job = self._enqueue_and_get_job(db_session, owner)
        notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()

        def _raise_not_configured():
            raise HTTPException(status_code=503, detail="Email sending is not configured.")

        monkeypatch.setattr("app.jobs.handlers.notification.get_email_sender", _raise_not_configured)

        result = handle_notification_email(
            db_session, job, NotificationEmailPayload(notification_id=notification.id)
        )

        assert result.outcome == JobOutcome.permanently_failed
        assert result.error_code == "email_not_configured"


class TestNotificationApi:
    def test_list_returns_only_the_current_users_own_notifications(self, db_session, client):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        member = make_member_in_org(db_session, owner.organization, email="member@example.com")
        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )

        resp = client.get(
            f"/organizations/{owner.organization.id}/notifications", headers=owner.auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["unread_count"] == 1
        assert body["items"][0]["title"] == "Customer created"

        member_resp = client.get(
            f"/organizations/{owner.organization.id}/notifications", headers=member.auth_headers
        )
        assert member_resp.json()["total"] == 1
        # Different Notification rows -- not the same id shared between users.
        assert member_resp.json()["items"][0]["id"] != body["items"][0]["id"]

    def test_unread_only_filter(self, db_session, client):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )
        notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()
        client.post(
            f"/organizations/{owner.organization.id}/notifications/{notification.id}/read",
            headers=owner.auth_headers,
        )

        resp = client.get(
            f"/organizations/{owner.organization.id}/notifications?unread_only=true",
            headers=owner.auth_headers,
        )
        assert resp.json()["total"] == 0
        assert resp.json()["unread_count"] == 0

    def test_mark_read_is_idempotent_and_sets_read_at(self, db_session, client):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )
        notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()

        resp = client.post(
            f"/organizations/{owner.organization.id}/notifications/{notification.id}/read",
            headers=owner.auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["read_at"] is not None
        first_read_at = resp.json()["read_at"]

        resp2 = client.post(
            f"/organizations/{owner.organization.id}/notifications/{notification.id}/read",
            headers=owner.auth_headers,
        )
        assert resp2.json()["read_at"] == first_read_at

    def test_mark_read_404s_for_another_users_notification(self, db_session, client):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        member = make_member_in_org(db_session, owner.organization, email="member@example.com")
        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )
        owners_notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()

        resp = client.post(
            f"/organizations/{owner.organization.id}/notifications/{owners_notification.id}/read",
            headers=member.auth_headers,
        )
        assert resp.status_code == 404

    def test_mark_read_404s_for_a_notification_in_another_organization(self, db_session, client):
        owner_a = make_org_with_owner(db_session, email="owner-a@example.com", org_name="Org A")
        owner_b = make_org_with_owner(db_session, email="owner-b@example.com", org_name="Org B")
        create_customer_record(
            db_session, owner_a.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )
        notification_a = db_session.query(Notification).filter_by(user_id=owner_a.user.id).one()

        resp = client.post(
            f"/organizations/{owner_b.organization.id}/notifications/{notification_a.id}/read",
            headers=owner_b.auth_headers,
        )
        assert resp.status_code == 404

    def test_read_all_marks_every_unread_notification(self, db_session, client):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        create_customer_record(
            db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
        )
        create_customer_record(
            db_session, owner.organization.id, name="Beta", email="b@example.com", phone="", address="", tax_id=""
        )

        resp = client.post(
            f"/organizations/{owner.organization.id}/notifications/read-all", headers=owner.auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["unread_count"] == 0
        assert resp.json()["total"] == 2

    def test_list_requires_organization_membership(self, db_session, client):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        outsider = make_user(db_session, email="outsider@example.com")
        from app.security import create_access_token

        resp = client.get(
            f"/organizations/{owner.organization.id}/notifications",
            headers={"Authorization": f"Bearer {create_access_token(outsider.id)}"},
        )
        assert resp.status_code == 403

    def test_preferences_default_to_email_enabled_true(self, db_session, client):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        resp = client.get(
            f"/organizations/{owner.organization.id}/notification-preferences", headers=owner.auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["email_enabled"] is True

    def test_patch_preferences_persists_the_opt_out(self, db_session, client):
        owner = make_org_with_owner(db_session, email="owner@example.com")
        patch_resp = client.patch(
            f"/organizations/{owner.organization.id}/notification-preferences",
            headers=owner.auth_headers,
            json={"email_enabled": False},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["email_enabled"] is False

        get_resp = client.get(
            f"/organizations/{owner.organization.id}/notification-preferences", headers=owner.auth_headers
        )
        assert get_resp.json()["email_enabled"] is False
