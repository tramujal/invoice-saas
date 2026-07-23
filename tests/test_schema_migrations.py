"""Idempotency coverage for app.schema_migrations -- this project has no
Alembic; every migration re-runs on every startup (see init_db()), so
each one must tolerate being applied to a database that already has the
change. Focused on _add_user_platform_role (the newest migration) rather
than the full list, which the session-scoped _test_database fixture
already exercises once at collection time.
"""

from sqlalchemy import inspect

from app.database import engine
from app.schema_migrations import run_startup_migrations


def test_add_user_platform_role_migration_is_idempotent():
    # The session-scoped _test_database fixture already ran every
    # migration once (via init_db()) before this test starts -- so
    # column-already-exists is exactly the case being exercised here by
    # running the whole list again.
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    columns = inspector.get_columns("users")
    platform_role_columns = [c for c in columns if c["name"] == "platform_role"]
    assert len(platform_role_columns) == 1


def test_add_organization_status_migration_is_idempotent_and_defaults_active(db_session):
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    columns = inspector.get_columns("organizations")
    status_columns = [c for c in columns if c["name"] == "status"]
    assert len(status_columns) == 1

    from tests.factories import make_organization

    organization = make_organization(db_session, name="Migration Default Check")
    assert organization.status == "active"


def test_platform_audit_log_table_migration_is_idempotent():
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    assert "platform_audit_log" in inspector.get_table_names()


def test_add_user_status_migration_is_idempotent_and_defaults_active(db_session):
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    status_columns = [c for c in inspector.get_columns("users") if c["name"] == "status"]
    assert len(status_columns) == 1

    from tests.factories import make_user

    user = make_user(db_session, email="migration-default-status@example.com")
    assert user.status == "active"


def test_platform_audit_log_user_target_and_details_migration_is_idempotent():
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("platform_audit_log")}
    assert {"target_user_id", "target_user_email", "details"}.issubset(columns)


def test_platform_audit_log_query_indexes_migration_is_idempotent():
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    index_names = {ix["name"] for ix in inspector.get_indexes("platform_audit_log")}
    assert {
        "ix_platform_audit_log_created_at",
        "ix_platform_audit_log_action",
        "ix_platform_audit_log_actor_user_id",
    }.issubset(index_names)


def test_platform_settings_table_migration_is_idempotent():
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    assert "platform_settings" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("platform_settings")}
    assert {
        "id",
        "maintenance_mode",
        "registrations_enabled",
        "ai_enabled",
        "emails_enabled",
        "invoice_reminders_enabled",
        "quote_reminders_enabled",
        "default_language",
        "default_currency",
        "updated_at",
        "updated_by_user_id",
        "version",
    }.issubset(columns)


def test_platform_settings_version_migration_is_idempotent_and_defaults_to_one(db_session):
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    version_columns = [c for c in inspector.get_columns("platform_settings") if c["name"] == "version"]
    assert len(version_columns) == 1

    from app.models import PLATFORM_SETTINGS_SINGLETON_ID, PlatformSettings

    # The singleton row is seeded once, at version 1, by conftest.py's
    # session-scoped _test_database fixture before any per-test
    # transaction begins -- see that fixture's own docstring.
    row = db_session.get(PlatformSettings, PLATFORM_SETTINGS_SINGLETON_ID)
    assert row is not None
    assert row.version == 1
