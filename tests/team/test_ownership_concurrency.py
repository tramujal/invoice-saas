"""C1 regression: the "at least one active owner always" invariant must
survive two concurrent demote/remove requests racing on the same
organization's last two owners.

Uses its own throwaway SQLite file + engine with a `BEGIN IMMEDIATE`
listener (not the shared, SAVEPOINT-nested `db_session`/`client`
fixtures, which bind every request in a test to one single connection)
so two real threads with independent connections genuinely serialize on
app.services.plan_limits._lock_organization's row lock -- exactly the
pattern tests/test_plan_limits.py::test_concurrent_requests_when_one_slot_remains
and tests/billing/test_subscription_concurrency.py already establish for
this same class of race."""

import os
import tempfile
import threading

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as RawSession

from app.membership_role import MembershipRole
from app.membership_status import MembershipStatus
from app.models import Base, Organization, OrganizationMember, User
from app.security import hash_password
from app.services.team import CannotRemoveLastOwnerError, remove_member_record


def _build_race_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="saas_owner_race_")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _disable_pysqlite_autocommit(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(engine)

    with RawSession(engine) as setup_db:
        org = Organization(name="Race Owners Co")
        setup_db.add(org)
        setup_db.flush()
        user_a = User(email="owner-a@race.test", hashed_password=hash_password("Correct-Horse-1"))
        user_b = User(email="owner-b@race.test", hashed_password=hash_password("Correct-Horse-1"))
        setup_db.add_all([user_a, user_b])
        setup_db.flush()
        membership_a = OrganizationMember(
            user_id=user_a.id,
            organization_id=org.id,
            role=MembershipRole.owner.value,
            status=MembershipStatus.active.value,
        )
        membership_b = OrganizationMember(
            user_id=user_b.id,
            organization_id=org.id,
            role=MembershipRole.owner.value,
            status=MembershipStatus.active.value,
        )
        setup_db.add_all([membership_a, membership_b])
        setup_db.commit()
        org_id, membership_a_id, membership_b_id = org.id, membership_a.id, membership_b.id

    def cleanup():
        engine.dispose()
        try:
            os.remove(path)
        except OSError:
            pass

    return engine, cleanup, org_id, membership_a_id, membership_b_id


def test_two_owners_racing_to_remove_each_other_leave_exactly_one_owner():
    """Two owners, each concurrently removing the OTHER -- without the
    row lock, both could read "one other owner remains" before either
    commits, leaving zero active owners. With it, exactly one removal
    must succeed and the other must fail with CannotRemoveLastOwnerError,
    and at least one active owner must remain afterward."""
    engine, cleanup, org_id, membership_a_id, membership_b_id = _build_race_db()
    try:
        barrier = threading.Barrier(2)
        results: dict[str, str] = {}

        def remove_b_as_a():
            with RawSession(engine) as db:
                barrier.wait()
                actor = db.get(OrganizationMember, membership_a_id)
                target = db.get(OrganizationMember, membership_b_id)
                try:
                    remove_member_record(db, org_id, target, actor)
                    results["a_removes_b"] = "success"
                except CannotRemoveLastOwnerError:
                    results["a_removes_b"] = "conflict"

        def remove_a_as_b():
            with RawSession(engine) as db:
                barrier.wait()
                actor = db.get(OrganizationMember, membership_b_id)
                target = db.get(OrganizationMember, membership_a_id)
                try:
                    remove_member_record(db, org_id, target, actor)
                    results["b_removes_a"] = "success"
                except CannotRemoveLastOwnerError:
                    results["b_removes_a"] = "conflict"

        t1 = threading.Thread(target=remove_b_as_a)
        t2 = threading.Thread(target=remove_a_as_b)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        outcomes = {results.get("a_removes_b"), results.get("b_removes_a")}
        assert outcomes == {"success", "conflict"}, results

        with RawSession(engine) as verify_db:
            active_owners = [
                m
                for m in verify_db.query(OrganizationMember).filter_by(organization_id=org_id).all()
                if m.status == MembershipStatus.active.value and m.role == MembershipRole.owner.value
            ]
            assert len(active_owners) == 1
    finally:
        cleanup()


def test_owner_demotion_and_removal_race_leave_exactly_one_owner():
    """Same invariant, exercised across the two different mutation paths
    (change_member_role_record's demotion vs. remove_member_record's
    removal) racing on the same pair of owners -- both go through the
    identical lock, so the invariant holds regardless of which mutation
    each side uses."""
    from app.membership_role import InvitationRole
    from app.services.team import change_member_role_record

    engine, cleanup, org_id, membership_a_id, membership_b_id = _build_race_db()
    try:
        barrier = threading.Barrier(2)
        results: dict[str, str] = {}

        def demote_b_as_a():
            with RawSession(engine) as db:
                barrier.wait()
                actor = db.get(OrganizationMember, membership_a_id)
                target = db.get(OrganizationMember, membership_b_id)
                try:
                    change_member_role_record(db, org_id, target, InvitationRole.member, actor)
                    results["a_demotes_b"] = "success"
                except CannotRemoveLastOwnerError:
                    results["a_demotes_b"] = "conflict"

        def remove_a_as_b():
            with RawSession(engine) as db:
                barrier.wait()
                actor = db.get(OrganizationMember, membership_b_id)
                target = db.get(OrganizationMember, membership_a_id)
                try:
                    remove_member_record(db, org_id, target, actor)
                    results["b_removes_a"] = "success"
                except CannotRemoveLastOwnerError:
                    results["b_removes_a"] = "conflict"

        t1 = threading.Thread(target=demote_b_as_a)
        t2 = threading.Thread(target=remove_a_as_b)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        outcomes = {results.get("a_demotes_b"), results.get("b_removes_a")}
        assert outcomes == {"success", "conflict"}, results

        with RawSession(engine) as verify_db:
            active_owners = [
                m
                for m in verify_db.query(OrganizationMember).filter_by(organization_id=org_id).all()
                if m.status == MembershipStatus.active.value and m.role == MembershipRole.owner.value
            ]
            assert len(active_owners) == 1
    finally:
        cleanup()
