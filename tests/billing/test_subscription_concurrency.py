"""Optimistic concurrency for Subscription mutations (Phase P2.1).

Unlike tests/platform_admin/test_plan_concurrency.py (which fakes a race
via two sequential HTTP calls sharing one connection, since Plan's own
version check happens in the router), these tests exercise
app.billing.service.BillingService directly with genuinely separate DB
connections -- BillingService's own protection comes from Subscription's
`version_id_col` mapper feature (see that model's own docstring), which
only manifests a real conflict when two ORM sessions have each already
loaded the same row before either commits. The shared, SAVEPOINT-nested
`db_session`/`client` fixtures used everywhere else in this suite bind
every request to ONE connection inside an uncommitted outer transaction
(see tests/conftest.py's own docstring), so a second, independent
connection would never see that data at all -- exactly like
tests/test_plan_limits.py::test_concurrent_requests_when_one_slot_remains,
these tests build their own throwaway SQLite file and engine instead."""

import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as RawSession

from app.billing.service import BillingService, SubscriptionConflictError
from app.billing_period import BillingPeriod
from app.models import Base, Organization, Plan, Subscription
from app.subscription_status import SubscriptionStatus


def _build_race_db():
    """Creates a fresh, throwaway SQLite file with the full schema plus
    one organization, two plans, and one active Subscription -- returns
    (engine, cleanup, subscription_id, plan_a_id, plan_b_id). Caller
    must invoke cleanup() when done (mirrors test_plan_limits.py's own
    try/finally around its equivalent setup)."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="saas_sub_concurrency_")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    with RawSession(engine) as setup_db:
        plan_a = Plan(code="race-a", name="Race Plan A", is_active=True, is_default=True, sort_order=0)
        plan_b = Plan(code="race-b", name="Race Plan B", is_active=True, sort_order=1)
        setup_db.add_all([plan_a, plan_b])
        setup_db.flush()
        org = Organization(name="Race Co", plan_id=plan_a.id)
        setup_db.add(org)
        setup_db.flush()
        now = datetime.now(timezone.utc)
        subscription = Subscription(
            organization_id=org.id,
            plan_id=plan_a.id,
            status=SubscriptionStatus.active.value,
            billing_period=BillingPeriod.monthly.value,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        setup_db.add(subscription)
        setup_db.commit()
        subscription_id, plan_a_id, plan_b_id = subscription.id, plan_a.id, plan_b.id

    def cleanup():
        engine.dispose()
        try:
            os.remove(path)
        except OSError:
            pass

    return engine, cleanup, subscription_id, plan_a_id, plan_b_id


def test_second_committer_on_a_stale_row_raises_subscription_conflict_error():
    """Deterministic (sequential, no threads) reproduction of two writers
    racing on the same subscription: both load the row while it's still
    at version 1, the first writer (an admin-style plan change) commits
    and advances it to version 2, and the second writer (a webhook-style
    cancellation) -- still holding its own, now-stale, in-memory
    version=1 -- must fail with SubscriptionConflictError rather than
    silently overwriting the first writer's change."""
    engine, cleanup, subscription_id, plan_a_id, plan_b_id = _build_race_db()
    try:
        session_admin = RawSession(engine)
        session_webhook = RawSession(engine)
        sub_admin = session_admin.get(Subscription, subscription_id)
        sub_webhook = session_webhook.get(Subscription, subscription_id)
        assert sub_admin.version == sub_webhook.version == 1

        plan_b = session_admin.get(Plan, plan_b_id)
        BillingService(session_admin).change_plan(sub_admin, plan_b)
        assert sub_admin.version == 2

        try:
            BillingService(session_webhook).cancel_immediately(sub_webhook)
            raise AssertionError("expected SubscriptionConflictError")
        except SubscriptionConflictError as exc:
            assert exc.current_version == 2

        session_admin.close()
        session_webhook.close()

        with RawSession(engine) as verify_db:
            final = verify_db.get(Subscription, subscription_id)
            assert final.version == 2
            assert final.plan_id == plan_b_id
            assert final.status == SubscriptionStatus.active.value  # the loser's cancel never applied
    finally:
        cleanup()


def test_second_committer_conflict_writes_no_subscription_event():
    """The loser's own SubscriptionEvent (queued via db.add() before the
    failed commit) must never persist -- _commit's rollback on
    StaleDataError discards the whole pending transaction, not just the
    Subscription row's own attribute changes. Uses cancel_immediately vs.
    change_plan (neither has a status precondition) rather than
    reactivate, since reactivate's own precondition check runs against
    the loser's already-stale in-memory status and would raise
    InvalidSubscriptionStateError before ever reaching _commit --
    a different, also-correct failure mode, just not the one this test
    targets."""
    engine, cleanup, subscription_id, plan_a_id, plan_b_id = _build_race_db()
    try:
        session_admin = RawSession(engine)
        session_webhook = RawSession(engine)
        sub_admin = session_admin.get(Subscription, subscription_id)
        sub_webhook = session_webhook.get(Subscription, subscription_id)

        BillingService(session_admin).cancel_immediately(sub_admin)

        try:
            plan_b = session_webhook.get(Plan, plan_b_id)
            BillingService(session_webhook).change_plan(sub_webhook, plan_b)
            raise AssertionError("expected SubscriptionConflictError")
        except SubscriptionConflictError:
            pass

        session_admin.close()
        session_webhook.close()

        with RawSession(engine) as verify_db:
            from app.models import SubscriptionEvent

            events = verify_db.query(SubscriptionEvent).filter_by(subscription_id=subscription_id).all()
            event_types = {e.event_type for e in events}
            assert "plan_upgraded" not in event_types
            assert "manual_adjustment" not in event_types
            assert "subscription_canceled" in event_types
    finally:
        cleanup()


def test_admin_plan_change_racing_webhook_cancellation_exactly_one_wins():
    """Genuine two-thread race with independent DB connections (see this
    file's own module docstring) -- a real
    threading.Barrier-synchronized reproduction of the exact scenario
    Phase P2.1 was written to close: a platform admin reassigning an
    organization's plan (BillingService.change_plan, mirroring
    app.routers.platform_admin.change_platform_subscription_plan) racing
    a Stripe webhook's cancellation (BillingService.cancel_immediately,
    the same method app.billing.service.BillingService
    .sync_from_webhook_event calls for a subscription_canceled event).
    Both threads load the row before either is allowed to proceed, so
    both start from the same version; the DB (via version_id_col) must
    let exactly one of the two commits through and reject the other with
    SubscriptionConflictError -- never let both silently apply, and
    never leave the row in a state that reflects only half of one
    writer's change."""
    engine, cleanup, subscription_id, plan_a_id, plan_b_id = _build_race_db()
    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def admin_plan_change():
            session = RawSession(engine)
            try:
                sub = session.get(Subscription, subscription_id)
                plan_b = session.get(Plan, plan_b_id)
                barrier.wait()
                try:
                    BillingService(session).change_plan(sub, plan_b)
                    results["admin"] = "success"
                except SubscriptionConflictError:
                    results["admin"] = "conflict"
            finally:
                session.close()

        def webhook_cancellation():
            session = RawSession(engine)
            try:
                sub = session.get(Subscription, subscription_id)
                barrier.wait()
                try:
                    BillingService(session).cancel_immediately(sub)
                    results["webhook"] = "success"
                except SubscriptionConflictError:
                    results["webhook"] = "conflict"
            finally:
                session.close()

        t_admin = threading.Thread(target=admin_plan_change)
        t_webhook = threading.Thread(target=webhook_cancellation)
        t_admin.start()
        t_webhook.start()
        t_admin.join(timeout=10)
        t_webhook.join(timeout=10)

        outcomes = {results.get("admin"), results.get("webhook")}
        assert outcomes == {"success", "conflict"}, results

        with RawSession(engine) as verify_db:
            final = verify_db.get(Subscription, subscription_id)
            assert final.version == 2
            if results["admin"] == "success":
                assert final.plan_id == plan_b_id
                assert final.status == SubscriptionStatus.active.value
            else:
                assert final.plan_id == plan_a_id
                assert final.status == SubscriptionStatus.canceled.value
    finally:
        cleanup()
