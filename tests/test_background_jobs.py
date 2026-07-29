"""Phase 15C -- Durable Background Jobs & Webhook Retry Execution.

Covers: the job domain model (enqueue/validate/idempotency/transaction
safety), claiming (atomic conditional UPDATE, priority/queue/
availability filtering, lease fields), execution (run_claimed_job's
success/retry/permanent-failure/malformed-payload/unknown-type paths),
crash recovery (lease expiration), the webhook.deliver/webhook.retry
handlers wired into the real durable queue (replacing Phase 15B's
ThreadPoolExecutor dispatcher), and the Platform Admin Jobs router.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.job_status import JobStatus
from app.job_type import JobType
from app.jobs.registry import JobOutcome, JobResult, UnknownJobTypeError, get_job_definition
from app.models import BackgroundJob, WebhookDelivery
from app.services.background_jobs import (
    InvalidJobPayloadError,
    claim_jobs,
    complete_job,
    enqueue_job,
    generate_worker_id,
    mark_started,
    recover_abandoned_jobs,
    run_claimed_job,
)
from app.services.customers import create_customer_record
from app.services.webhook_deliveries import (
    MAX_WEBHOOK_DELIVERY_ATTEMPTS,
    create_next_delivery_attempt,
    is_retryable_failure,
)
from app.services.webhook_endpoints import create_endpoint
from app.services.webhook_events import record_webhook_event
from app.webhook_delivery_status import WebhookDeliveryStatus
from app.webhook_delivery_trigger import WebhookDeliveryTrigger
from app.webhook_event_type import WebhookEventType

from tests.factories import make_org_with_owner, make_plan, make_subscription


def _make_webhook_endpoint(db, owner, *, events=None):
    """Phase 17B enforces app.services.plan_limits.LimitedResource.webhooks
    at creation time, and app.services.webhook_events.record_webhook_event
    silently drops deliveries when background_jobs_enabled is false --
    make_org_with_owner's default (Free-tier) subscription has both
    max_webhooks=0 and background_jobs_enabled=False, so bump the org
    onto a plan with both raised first."""
    plan = make_plan(
        db,
        code=f"webhooks-ok-{owner.organization.id}",
        max_webhooks=None,
        max_api_keys=None,
        background_jobs_enabled=True,
    )
    make_subscription(db, owner.organization, plan=plan)
    endpoint, _secret = create_endpoint(
        db,
        owner.organization.id,
        owner.user,
        url="https://example.com/hook",
        description="",
        subscribed_events=events or frozenset({WebhookEventType.customer_created}),
    )
    return endpoint


# --- app.services.background_jobs: enqueue -----------------------------------


class TestEnqueueJob:
    def test_enqueue_persists_row_with_expected_defaults(self, db_session):
        owner = make_org_with_owner(db_session, email="ej1@example.com", org_name="Ej1 Co")
        job = enqueue_job(
            db_session,
            job_type=JobType.webhook_deliver,
            payload={"delivery_id": "does-not-need-to-exist-for-this-test"},
            organization_id=owner.organization.id,
        )
        db_session.commit()
        assert job is not None
        assert job.status == JobStatus.pending.value
        assert job.job_type == "webhook.deliver"
        assert job.queue == "default"
        assert job.attempts == 0
        assert json.loads(job.payload) == {"delivery_id": "does-not-need-to-exist-for-this-test"}

    def test_unknown_job_type_raises(self, db_session):
        owner = make_org_with_owner(db_session, email="ej2@example.com", org_name="Ej2 Co")
        with pytest.raises(UnknownJobTypeError):
            get_job_definition("not.a.real.job.type")

    def test_invalid_payload_raises(self, db_session):
        owner = make_org_with_owner(db_session, email="ej3@example.com", org_name="Ej3 Co")
        with pytest.raises(InvalidJobPayloadError):
            enqueue_job(
                db_session,
                job_type=JobType.webhook_deliver,
                payload={"wrong_field": "x"},  # missing required delivery_id
                organization_id=owner.organization.id,
            )

    def test_missing_organization_id_raises_when_required(self, db_session):
        with pytest.raises(ValueError):
            enqueue_job(
                db_session,
                job_type=JobType.webhook_deliver,
                payload={"delivery_id": "x"},
                organization_id=None,
            )

    def test_duplicate_idempotency_key_is_a_silent_noop(self, db_session):
        owner = make_org_with_owner(db_session, email="ej4@example.com", org_name="Ej4 Co")
        first = enqueue_job(
            db_session,
            job_type=JobType.webhook_deliver,
            payload={"delivery_id": "d1"},
            organization_id=owner.organization.id,
            idempotency_key="webhook-delivery:d1",
        )
        db_session.commit()
        second = enqueue_job(
            db_session,
            job_type=JobType.webhook_deliver,
            payload={"delivery_id": "d1"},
            organization_id=owner.organization.id,
            idempotency_key="webhook-delivery:d1",
        )
        assert first is not None
        assert second is None
        count = db_session.query(BackgroundJob).filter_by(idempotency_key="webhook-delivery:d1").count()
        assert count == 1

    def test_rollback_removes_the_job_row(self, db_session):
        owner = make_org_with_owner(db_session, email="ej5@example.com", org_name="Ej5 Co")
        try:
            with db_session.begin_nested():
                job = enqueue_job(
                    db_session,
                    job_type=JobType.webhook_deliver,
                    payload={"delivery_id": "will-be-rolled-back"},
                    organization_id=owner.organization.id,
                )
                job_id = job.id
                db_session.flush()
                raise _RollbackMe()
        except _RollbackMe:
            pass
        assert db_session.get(BackgroundJob, job_id) is None


class _RollbackMe(Exception):
    pass


# --- app.services.background_jobs: claiming -----------------------------------


class TestClaimJobs:
    def _enqueue(self, db, owner, **overrides):
        defaults = dict(
            job_type=JobType.webhook_deliver,
            payload={"delivery_id": "x"},
            organization_id=owner.organization.id,
        )
        defaults.update(overrides)
        job = enqueue_job(db, **defaults)
        db.commit()
        return job

    def test_claims_available_job(self, db_session):
        owner = make_org_with_owner(db_session, email="cj1@example.com", org_name="Cj1 Co")
        job = self._enqueue(db_session, owner)
        worker_id = generate_worker_id()
        claimed = claim_jobs(db_session, worker_id=worker_id)
        assert len(claimed) == 1
        assert claimed[0].id == job.id
        assert claimed[0].status == JobStatus.claimed.value
        assert claimed[0].claimed_by == worker_id
        assert claimed[0].lease_expires_at is not None

    def test_second_claim_gets_nothing(self, db_session):
        owner = make_org_with_owner(db_session, email="cj2@example.com", org_name="Cj2 Co")
        self._enqueue(db_session, owner)
        claim_jobs(db_session, worker_id="worker-a")
        second = claim_jobs(db_session, worker_id="worker-b")
        assert second == []

    def test_future_available_at_not_claimed(self, db_session):
        owner = make_org_with_owner(db_session, email="cj3@example.com", org_name="Cj3 Co")
        self._enqueue(db_session, owner, available_at=datetime.now(timezone.utc) + timedelta(hours=1))
        claimed = claim_jobs(db_session, worker_id="worker-a")
        assert claimed == []

    def test_different_queue_not_claimed(self, db_session):
        owner = make_org_with_owner(db_session, email="cj4@example.com", org_name="Cj4 Co")
        self._enqueue(db_session, owner)
        claimed = claim_jobs(db_session, worker_id="worker-a", queue="other-queue")
        assert claimed == []

    def test_batch_size_respected(self, db_session):
        owner = make_org_with_owner(db_session, email="cj5@example.com", org_name="Cj5 Co")
        for i in range(3):
            self._enqueue(db_session, owner, idempotency_key=f"cj5-{i}")
        claimed = claim_jobs(db_session, worker_id="worker-a", batch_size=2)
        assert len(claimed) == 2

    def test_priority_ordering(self, db_session):
        owner = make_org_with_owner(db_session, email="cj6@example.com", org_name="Cj6 Co")
        low = self._enqueue(db_session, owner, idempotency_key="cj6-low")
        low.priority = 0
        db_session.commit()
        # enqueue_job doesn't take priority directly (it comes from the
        # JobDefinition) -- bump one row's priority directly to simulate
        # a higher-priority job for ordering purposes.
        high = self._enqueue(db_session, owner, idempotency_key="cj6-high")
        high.priority = 10
        db_session.commit()

        claimed = claim_jobs(db_session, worker_id="worker-a", batch_size=1)
        assert claimed[0].id == high.id


# --- app.services.background_jobs: execution -----------------------------------


class TestRunClaimedJob:
    def test_success_marks_succeeded(self, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="rc1@example.com", org_name="Rc1 Co")
        endpoint = _make_webhook_endpoint(db_session, owner)
        customer = create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        delivery = db_session.query(WebhookDelivery).filter_by(endpoint_id=endpoint.id).one()
        job = db_session.query(BackgroundJob).filter_by(job_type="webhook.deliver").one()

        class _FakeResponse:
            status_code = 200
            content = b"ok"

        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post", lambda *a, **kw: _FakeResponse()
        )

        claimed = claim_jobs(db_session, worker_id="w1")
        assert claimed[0].id == job.id
        result = run_claimed_job(db_session, claimed[0])
        assert result.outcome == JobOutcome.succeeded
        db_session.refresh(job)
        assert job.status == JobStatus.succeeded.value
        assert job.completed_at is not None

    def test_malformed_payload_is_permanently_failed(self, db_session):
        owner = make_org_with_owner(db_session, email="rc2@example.com", org_name="Rc2 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload=json.dumps({"not_delivery_id": "x"}),
            status=JobStatus.pending.value,
        )
        db_session.add(job)
        db_session.commit()

        claimed = claim_jobs(db_session, worker_id="w1")
        result = run_claimed_job(db_session, claimed[0])
        assert result.outcome == JobOutcome.permanently_failed
        assert result.error_code == "invalid_payload"
        db_session.refresh(job)
        assert job.status == JobStatus.permanently_failed.value

    def test_unknown_job_type_is_permanently_failed(self, db_session):
        owner = make_org_with_owner(db_session, email="rc3@example.com", org_name="Rc3 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="not.a.real.type",
            payload="{}",
            status=JobStatus.pending.value,
        )
        db_session.add(job)
        db_session.commit()

        result = run_claimed_job(db_session, job)
        assert result.outcome == JobOutcome.permanently_failed
        assert result.error_code == "unknown_job_type"

    def test_handler_exception_is_retryable(self, db_session):
        owner = make_org_with_owner(db_session, email="rc4@example.com", org_name="Rc4 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload=json.dumps({"delivery_id": "does-not-exist"}),
            status=JobStatus.pending.value,
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()

        claimed = claim_jobs(db_session, worker_id="w1")
        # deliver_webhook raises DeliveryNotFoundError for a nonexistent
        # delivery_id -- a genuine handler exception, correctly treated as
        # a retryable job-execution failure (never a webhook business
        # outcome, since there's no delivery row to record one on).
        result = run_claimed_job(db_session, claimed[0])
        assert result.outcome == JobOutcome.retry
        db_session.refresh(job)
        assert job.status == JobStatus.retry_scheduled.value
        assert job.attempts == 1

    def test_attempts_exhausted_becomes_permanently_failed(self, db_session):
        owner = make_org_with_owner(db_session, email="rc5@example.com", org_name="Rc5 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload=json.dumps({"delivery_id": "does-not-exist"}),
            status=JobStatus.claimed.value,
            attempts=4,
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()

        result = run_claimed_job(db_session, job)
        assert result.outcome == JobOutcome.retry
        db_session.refresh(job)
        assert job.attempts == 5
        assert job.status == JobStatus.permanently_failed.value
        assert job.failed_at is not None


# --- app.services.background_jobs: complete_job state machine ------------------


class TestCompleteJob:
    def test_succeeded_clears_error_fields(self, db_session):
        owner = make_org_with_owner(db_session, email="cs1@example.com", org_name="Cs1 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload="{}",
            status=JobStatus.running.value,
            last_error_code="stale",
            last_error_message="stale message",
        )
        db_session.add(job)
        db_session.commit()

        complete_job(db_session, job, JobResult(outcome=JobOutcome.succeeded, result_summary="ok"))
        assert job.status == JobStatus.succeeded.value
        assert job.last_error_code is None
        assert job.last_error_message is None
        assert job.claimed_by is None
        assert job.lease_expires_at is None

    def test_retry_schedules_future_available_at(self, db_session):
        owner = make_org_with_owner(db_session, email="cs2@example.com", org_name="Cs2 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload="{}",
            status=JobStatus.running.value,
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()

        before = datetime.now(timezone.utc)
        complete_job(db_session, job, JobResult(outcome=JobOutcome.retry, error_code="boom"))
        assert job.status == JobStatus.retry_scheduled.value
        assert job.attempts == 1
        assert job.available_at.replace(tzinfo=timezone.utc) > before

    def test_retry_after_override_is_respected(self, db_session):
        owner = make_org_with_owner(db_session, email="cs3@example.com", org_name="Cs3 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload="{}",
            status=JobStatus.running.value,
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()

        complete_job(
            db_session, job, JobResult(outcome=JobOutcome.retry, retry_after=timedelta(hours=6))
        )
        delta = job.available_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        assert timedelta(hours=5, minutes=55) < delta <= timedelta(hours=6, minutes=1)


# --- app.services.background_jobs: crash recovery -------------------------------


class TestRecoverAbandonedJobs:
    def test_expired_claimed_job_recovered(self, db_session):
        owner = make_org_with_owner(db_session, email="ra1@example.com", org_name="Ra1 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload="{}",
            status=JobStatus.claimed.value,
            claimed_by="dead-worker",
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            attempts=0,
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()

        recovered_count = recover_abandoned_jobs(db_session)
        assert recovered_count == 1
        db_session.refresh(job)
        assert job.status == JobStatus.pending.value
        assert job.attempts == 1
        assert job.claimed_by is None
        assert job.lease_expires_at is None

    def test_expired_running_job_recovered(self, db_session):
        owner = make_org_with_owner(db_session, email="ra2@example.com", org_name="Ra2 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload="{}",
            status=JobStatus.running.value,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()
        assert recover_abandoned_jobs(db_session) == 1
        db_session.refresh(job)
        assert job.status == JobStatus.pending.value

    def test_non_expired_job_not_touched(self, db_session):
        owner = make_org_with_owner(db_session, email="ra3@example.com", org_name="Ra3 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload="{}",
            status=JobStatus.claimed.value,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db_session.add(job)
        db_session.commit()
        assert recover_abandoned_jobs(db_session) == 0
        db_session.refresh(job)
        assert job.status == JobStatus.claimed.value

    def test_exhausted_attempts_becomes_permanently_failed(self, db_session):
        owner = make_org_with_owner(db_session, email="ra4@example.com", org_name="Ra4 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload="{}",
            status=JobStatus.claimed.value,
            attempts=4,
            max_attempts=5,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db_session.add(job)
        db_session.commit()
        assert recover_abandoned_jobs(db_session) == 1
        db_session.refresh(job)
        assert job.status == JobStatus.permanently_failed.value
        assert job.attempts == 5

    def test_second_recovery_sweep_finds_nothing(self, db_session):
        owner = make_org_with_owner(db_session, email="ra5@example.com", org_name="Ra5 Co")
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload="{}",
            status=JobStatus.claimed.value,
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_attempts=5,
        )
        db_session.add(job)
        db_session.commit()
        assert recover_abandoned_jobs(db_session) == 1
        assert recover_abandoned_jobs(db_session) == 0  # already recovered, not double-counted


# --- webhook.deliver / webhook.retry handlers via the real durable queue -------


class TestWebhookJobHandlers:
    def test_initial_delivery_runs_via_worker_claim(self, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="wh1@example.com", org_name="Wh1 Co")
        _make_webhook_endpoint(db_session, owner)
        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        job = db_session.query(BackgroundJob).filter_by(job_type="webhook.deliver").one()
        assert job.status == JobStatus.pending.value

        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: type("R", (), {"status_code": 500, "content": b"err"})(),
        )
        claimed = claim_jobs(db_session, worker_id="w1")
        result = run_claimed_job(db_session, claimed[0])
        assert result.outcome == JobOutcome.succeeded  # job ran fine; the WEBHOOK failed
        assert "retry_scheduled" in result.result_summary

        # A webhook.retry job should now exist, scheduled for the future.
        retry_job = db_session.query(BackgroundJob).filter_by(job_type="webhook.retry").one()
        assert retry_job.status == JobStatus.pending.value
        assert retry_job.available_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    def test_retry_not_claimable_before_due(self, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="wh2@example.com", org_name="Wh2 Co")
        _make_webhook_endpoint(db_session, owner)
        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: type("R", (), {"status_code": 500, "content": b"err"})(),
        )
        first_job = claim_jobs(db_session, worker_id="w1")[0]
        run_claimed_job(db_session, first_job)

        retry_job = db_session.query(BackgroundJob).filter_by(job_type="webhook.retry").one()

        # This same customer.created event also enqueued a
        # notification.email job (see app.notifications.service
        # .emit_event), which has no artificial backoff and may still be
        # legitimately claimable -- drain anything else due first so this
        # test asserts only what it's actually about: the webhook retry
        # specifically must not be claimable before its own backoff delay.
        while True:
            claimed = claim_jobs(db_session, worker_id="w1")
            if not claimed:
                break
            assert claimed[0].id != retry_job.id
            run_claimed_job(db_session, claimed[0])

        db_session.refresh(retry_job)
        assert retry_job.status == JobStatus.pending.value

    def test_retry_fires_when_due_and_creates_new_delivery_row(self, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="wh3@example.com", org_name="Wh3 Co")
        _make_webhook_endpoint(db_session, owner)
        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: type("R", (), {"status_code": 500, "content": b"err"})(),
        )
        first_job = claim_jobs(db_session, worker_id="w1")[0]
        run_claimed_job(db_session, first_job)

        retry_job = db_session.query(BackgroundJob).filter_by(job_type="webhook.retry").one()
        # Force it due now (bypassing the real backoff wait, for the test).
        retry_job.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()

        claimed = claim_jobs(db_session, worker_id="w1")
        assert claimed[0].id == retry_job.id
        run_claimed_job(db_session, claimed[0])

        deliveries = db_session.query(WebhookDelivery).order_by(WebhookDelivery.attempt_number).all()
        assert len(deliveries) == 2
        assert deliveries[0].attempt_number == 1
        assert deliveries[1].attempt_number == 2
        assert deliveries[1].trigger == WebhookDeliveryTrigger.automatic_retry.value
        assert deliveries[0].event_id == deliveries[1].event_id  # same immutable event id

    def test_non_retryable_4xx_does_not_schedule_a_retry(self, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="wh4@example.com", org_name="Wh4 Co")
        _make_webhook_endpoint(db_session, owner)
        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: type("R", (), {"status_code": 404, "content": b"not found"})(),
        )
        job = claim_jobs(db_session, worker_id="w1")[0]
        run_claimed_job(db_session, job)
        assert db_session.query(BackgroundJob).filter_by(job_type="webhook.retry").count() == 0

    def test_max_attempts_ceiling_stops_retry_chain(self, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="wh5@example.com", org_name="Wh5 Co")
        _make_webhook_endpoint(db_session, owner)
        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: type("R", (), {"status_code": 500, "content": b"err"})(),
        )
        job = claim_jobs(db_session, worker_id="w1")[0]
        run_claimed_job(db_session, job)

        # Drive the chain forward until MAX_WEBHOOK_DELIVERY_ATTEMPTS is
        # reached, forcing each retry job due immediately.
        for _ in range(MAX_WEBHOOK_DELIVERY_ATTEMPTS - 1):
            pending_retry = (
                db_session.query(BackgroundJob)
                .filter_by(job_type="webhook.retry", status=JobStatus.pending.value)
                .order_by(BackgroundJob.created_at.desc())
                .first()
            )
            if pending_retry is None:
                break
            pending_retry.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db_session.commit()
            claimed = claim_jobs(db_session, worker_id="w1")
            run_claimed_job(db_session, claimed[0])

        deliveries = db_session.query(WebhookDelivery).order_by(WebhookDelivery.attempt_number).all()
        assert len(deliveries) == MAX_WEBHOOK_DELIVERY_ATTEMPTS
        assert all(d.status == WebhookDeliveryStatus.failed.value for d in deliveries)
        # No further retry job past the ceiling.
        assert (
            db_session.query(BackgroundJob)
            .filter_by(job_type="webhook.retry", status=JobStatus.pending.value)
            .count()
            == 0
        )

    def test_disabled_endpoint_stops_retry_chain(self, db_session, monkeypatch):
        owner = make_org_with_owner(db_session, email="wh6@example.com", org_name="Wh6 Co")
        endpoint = _make_webhook_endpoint(db_session, owner)
        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: type("R", (), {"status_code": 500, "content": b"err"})(),
        )
        job = claim_jobs(db_session, worker_id="w1")[0]
        run_claimed_job(db_session, job)

        endpoint.enabled = False
        db_session.commit()

        retry_job = db_session.query(BackgroundJob).filter_by(job_type="webhook.retry").one()
        retry_job.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()

        claimed = claim_jobs(db_session, worker_id="w1")
        result = run_claimed_job(db_session, claimed[0])
        assert result.outcome == JobOutcome.succeeded
        assert "terminal_endpoint_unavailable" in result.result_summary
        # Still only 1 delivery row -- no second attempt row was created.
        assert db_session.query(WebhookDelivery).count() == 1

    def test_retry_no_ops_if_already_succeeded(self, db_session, monkeypatch):
        """Simulates a race: a manual resend already succeeded before the
        scheduled automatic retry fires."""
        owner = make_org_with_owner(db_session, email="wh7@example.com", org_name="Wh7 Co")
        _make_webhook_endpoint(db_session, owner)
        create_customer_record(
            db_session, owner.organization.id, name="A", email="a@example.com", phone="", address="", tax_id=""
        )
        monkeypatch.setattr(
            "app.services.webhook_deliveries.requests.post",
            lambda *a, **kw: type("R", (), {"status_code": 500, "content": b"err"})(),
        )
        job = claim_jobs(db_session, worker_id="w1")[0]
        run_claimed_job(db_session, job)

        failed_delivery = db_session.query(WebhookDelivery).filter_by(attempt_number=1).one()
        failed_delivery.status = WebhookDeliveryStatus.succeeded.value  # simulate external resolution
        db_session.commit()

        retry_job = db_session.query(BackgroundJob).filter_by(job_type="webhook.retry").one()
        retry_job.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()
        claimed = claim_jobs(db_session, worker_id="w1")
        result = run_claimed_job(db_session, claimed[0])
        assert result.outcome == JobOutcome.succeeded
        assert result.result_summary == "already_succeeded_before_retry_due"
        assert db_session.query(WebhookDelivery).count() == 1  # no new row created


# --- app.services.webhook_deliveries: retry classification ---------------------


class TestRetryClassification:
    def _delivery(self, **overrides):
        d = WebhookDelivery(
            organization_id="org",
            event_id="evt",
            endpoint_id="ep",
            status=WebhookDeliveryStatus.failed.value,
            trigger=WebhookDeliveryTrigger.automatic.value,
            attempt_number=1,
            request_url="https://example.com",
        )
        for k, v in overrides.items():
            setattr(d, k, v)
        return d

    @pytest.mark.parametrize("code", [408, 425, 429, 500, 502, 503])
    def test_retryable_status_codes(self, code):
        assert is_retryable_failure(self._delivery(response_status_code=code)) is True

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 405, 410, 422])
    def test_non_retryable_status_codes(self, code):
        assert is_retryable_failure(self._delivery(response_status_code=code)) is False

    def test_unsafe_target_is_non_retryable(self):
        assert is_retryable_failure(self._delivery(error_message="unsafe_target_url")) is False

    def test_network_exception_is_retryable(self):
        assert is_retryable_failure(self._delivery(error_message="ConnectionError: refused")) is True


# --- Platform Admin Jobs router --------------------------------------------------


class TestPlatformJobsRouter:
    def _make_terminal_job(self, db_session, owner, status):
        job = BackgroundJob(
            organization_id=owner.organization.id,
            job_type="webhook.deliver",
            payload=json.dumps({"delivery_id": "x"}),
            status=status,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        return job

    def _platform_admin_headers(self, db_session, client):
        from app.platform_permissions import PlatformRole
        from tests.factories import make_user
        from app.security import create_access_token

        admin = make_user(db_session, email="platformadmin-jobs@example.com")
        admin.platform_role = PlatformRole.super_admin.value
        db_session.commit()
        return {"Authorization": f"Bearer {create_access_token(admin.id)}"}

    def test_list_requires_platform_permission(self, client, db_session):
        owner = make_org_with_owner(db_session, email="pj1@example.com", org_name="Pj1 Co")
        resp = client.get("/admin/jobs", headers=owner.auth_headers)
        assert resp.status_code == 403

    def test_list_and_filter_by_status(self, client, db_session):
        owner = make_org_with_owner(db_session, email="pj2@example.com", org_name="Pj2 Co")
        self._make_terminal_job(db_session, owner, JobStatus.permanently_failed.value)
        headers = self._platform_admin_headers(db_session, client)
        resp = client.get("/admin/jobs", params={"status": "permanently_failed"}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "permanently_failed" for item in body["items"])

    def test_detail_exposes_payload(self, client, db_session):
        owner = make_org_with_owner(db_session, email="pj3@example.com", org_name="Pj3 Co")
        job = self._make_terminal_job(db_session, owner, JobStatus.pending.value)
        headers = self._platform_admin_headers(db_session, client)
        resp = client.get(f"/admin/jobs/{job.id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["payload"] == {"delivery_id": "x"}

    def test_retry_permanently_failed_job_creates_new_job(self, client, db_session):
        owner = make_org_with_owner(db_session, email="pj4@example.com", org_name="Pj4 Co")
        job = self._make_terminal_job(db_session, owner, JobStatus.permanently_failed.value)
        headers = self._platform_admin_headers(db_session, client)
        resp = client.post(f"/admin/jobs/{job.id}/retry", json={"reason": "operator retry"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["id"] != job.id
        assert resp.json()["status"] == "pending"

    def test_retry_rejects_wrong_status(self, client, db_session):
        owner = make_org_with_owner(db_session, email="pj5@example.com", org_name="Pj5 Co")
        job = self._make_terminal_job(db_session, owner, JobStatus.pending.value)
        headers = self._platform_admin_headers(db_session, client)
        resp = client.post(f"/admin/jobs/{job.id}/retry", json={"reason": "x"}, headers=headers)
        assert resp.status_code == 409

    def test_cancel_pending_job(self, client, db_session):
        owner = make_org_with_owner(db_session, email="pj6@example.com", org_name="Pj6 Co")
        job = self._make_terminal_job(db_session, owner, JobStatus.pending.value)
        headers = self._platform_admin_headers(db_session, client)
        resp = client.post(f"/admin/jobs/{job.id}/cancel", json={"reason": "no longer needed"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_rejects_wrong_status(self, client, db_session):
        owner = make_org_with_owner(db_session, email="pj7@example.com", org_name="Pj7 Co")
        job = self._make_terminal_job(db_session, owner, JobStatus.succeeded.value)
        headers = self._platform_admin_headers(db_session, client)
        resp = client.post(f"/admin/jobs/{job.id}/cancel", json={"reason": "x"}, headers=headers)
        assert resp.status_code == 409

    def test_organization_filter_scopes_results(self, client, db_session):
        owner_a = make_org_with_owner(db_session, email="pj8a@example.com", org_name="Pj8a Co")
        owner_b = make_org_with_owner(db_session, email="pj8b@example.com", org_name="Pj8b Co")
        self._make_terminal_job(db_session, owner_a, JobStatus.pending.value)
        self._make_terminal_job(db_session, owner_b, JobStatus.pending.value)
        headers = self._platform_admin_headers(db_session, client)
        resp = client.get("/admin/jobs", params={"organization_id": owner_a.organization.id}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert all(item["organization_id"] == owner_a.organization.id for item in body["items"])
