"""Idempotency coverage for app.schema_migrations -- this project has no
Alembic; every migration re-runs on every startup (see init_db()), so
each one must tolerate being applied to a database that already has the
change. Focused on _add_user_platform_role (the newest migration) rather
than the full list, which the session-scoped _test_database fixture
already exercises once at collection time.
"""

from sqlalchemy import inspect, text

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


def test_plans_table_migration_is_idempotent():
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    assert "plans" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("plans")}
    assert {
        "id",
        "code",
        "name",
        "description",
        "is_active",
        "is_default",
        "sort_order",
        "max_users",
        "max_customers",
        "max_products",
        "max_invoices_per_month",
        "max_quotes_per_month",
        "max_ai_actions_per_month",
        "storage_limit_mb",
        "custom_branding_enabled",
        "api_access_enabled",
        "advanced_reports_enabled",
        "version",
        "created_at",
        "updated_at",
    }.issubset(columns)


def test_seed_default_plans_is_idempotent_and_creates_exactly_one_default(db_session):
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    from app.models import Plan

    rows = db_session.query(Plan).order_by(Plan.sort_order).all()
    codes = [row.code for row in rows]
    assert codes == ["free", "starter", "pro", "enterprise"]

    defaults = [row for row in rows if row.is_default]
    assert len(defaults) == 1
    assert defaults[0].code == "free"

    free = rows[0]
    assert free.max_users == 2
    assert free.max_customers == 100
    assert free.max_ai_actions_per_month == 25
    assert free.custom_branding_enabled is False

    enterprise = rows[3]
    assert enterprise.max_users is None
    assert enterprise.max_customers is None
    assert enterprise.custom_branding_enabled is True
    assert enterprise.api_access_enabled is True
    assert enterprise.advanced_reports_enabled is True


def test_seed_default_plans_never_overwrites_an_operator_edit(db_session):
    from app.models import Plan

    run_startup_migrations(engine)
    free = db_session.query(Plan).filter_by(code="free").one()
    free.max_users = 999
    db_session.commit()

    # Re-running startup migrations must not reset an operator's edit --
    # the seed step only inserts plans missing by code, never updates.
    run_startup_migrations(engine)

    db_session.refresh(free)
    assert free.max_users == 999


def test_organization_plan_id_migration_is_idempotent_and_backfills_free(db_session):
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    plan_id_columns = [c for c in inspector.get_columns("organizations") if c["name"] == "plan_id"]
    assert len(plan_id_columns) == 1

    from tests.factories import make_organization

    organization = make_organization(db_session, name="Migration Default Plan Check")
    assert organization.plan_id == "plan_free"


def test_document_customer_snapshot_migration_is_idempotent(db_session):
    run_startup_migrations(engine)
    run_startup_migrations(engine)

    inspector = inspect(engine)
    for table in ("invoices", "quotes"):
        columns = {c["name"] for c in inspector.get_columns(table)}
        for snapshot_column in (
            "customer_name_snapshot",
            "customer_email_snapshot",
            "customer_phone_snapshot",
            "customer_address_snapshot",
        ):
            assert snapshot_column in columns


def test_add_document_customer_snapshots_backfills_pre_existing_rows_on_sqlite():
    """Builds the exact pre-migration shape by hand (see
    test_add_organization_plan_id_alters_a_real_pre_existing_table_on_sqlite's
    identical rationale): a fresh sqlite engine with "customers" and
    "invoices"/"quotes" tables predating the 4 snapshot columns, one
    customer, and one invoice/quote already linked to it -- so both the
    ALTER TABLE path and the backfill UPDATE are actually exercised, not
    just the ordinary create_all()-already-has-the-columns case every
    other test in this module runs against."""
    from sqlalchemy import create_engine

    from app.schema_migrations import _add_document_customer_snapshots

    throwaway = create_engine("sqlite:///:memory:")
    with throwaway.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE customers (id CHAR(36) PRIMARY KEY, name VARCHAR(255), "
                "email VARCHAR(255), phone VARCHAR(64), address VARCHAR(512))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO customers (id, name, email, phone, address) VALUES "
                "('cust-1', 'Jane Doe', 'jane@example.com', '555-1234', '1 Main St')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE invoices (id CHAR(36) PRIMARY KEY, customer_id CHAR(36))"
            )
        )
        conn.execute(text("INSERT INTO invoices (id, customer_id) VALUES ('inv-1', 'cust-1')"))
        conn.execute(
            text("CREATE TABLE quotes (id CHAR(36) PRIMARY KEY, customer_id CHAR(36))")
        )
        conn.execute(text("INSERT INTO quotes (id, customer_id) VALUES ('quote-1', 'cust-1')"))

    _add_document_customer_snapshots(throwaway)

    with throwaway.begin() as conn:
        invoice_row = conn.execute(
            text("SELECT customer_name_snapshot, customer_email_snapshot, "
                 "customer_phone_snapshot, customer_address_snapshot FROM invoices WHERE id = 'inv-1'")
        ).one()
        quote_row = conn.execute(
            text("SELECT customer_name_snapshot, customer_email_snapshot, "
                 "customer_phone_snapshot, customer_address_snapshot FROM quotes WHERE id = 'quote-1'")
        ).one()

    assert invoice_row == ("Jane Doe", "jane@example.com", "555-1234", "1 Main St")
    assert quote_row == ("Jane Doe", "jane@example.com", "555-1234", "1 Main St")

    # Re-running must not error and must not clobber an already-backfilled
    # row -- the WHERE customer_name_snapshot IS NULL guard skips it.
    _add_document_customer_snapshots(throwaway)
    with throwaway.begin() as conn:
        invoice_row_again = conn.execute(
            text("SELECT customer_name_snapshot FROM invoices WHERE id = 'inv-1'")
        ).scalar()
    assert invoice_row_again == "Jane Doe"


def test_add_organization_plan_id_alters_a_real_pre_existing_table_on_sqlite():
    # The main engine's "organizations" table already has plan_id by the
    # time any test runs (init_db()'s create_all() creates it fresh, from
    # the current ORM model, before run_startup_migrations ever gets a
    # chance to run) -- so the ALTER TABLE branch this migration actually
    # exists for is never reached by the test above, or by any other test
    # in this module. That gap let a real bug through once already: SQLite
    # rejects "ADD COLUMN ... NOT NULL DEFAULT ... REFERENCES ..." as one
    # statement ("Cannot add a REFERENCES column with non-NULL default
    # value"), which only surfaced when starting the app against a dev
    # database created before this migration existed. This test builds
    # that exact pre-migration shape by hand -- a fresh sqlite engine with
    # "plans" and "organizations" tables where organizations predates
    # plan_id -- so the ALTER path is actually exercised.
    from sqlalchemy import create_engine

    from app.schema_migrations import _add_organization_plan_id, _add_plans_table, _seed_default_plans

    throwaway = create_engine("sqlite:///:memory:")
    with throwaway.begin() as conn:
        conn.execute(text("CREATE TABLE organizations (id CHAR(36) PRIMARY KEY, name VARCHAR(255))"))
        conn.execute(text("INSERT INTO organizations (id, name) VALUES ('org-1', 'Pre-existing Org')"))

    _add_plans_table(throwaway)
    _seed_default_plans(throwaway)
    _add_organization_plan_id(throwaway)

    inspector = inspect(throwaway)
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    assert "plan_id" in columns

    with throwaway.begin() as conn:
        plan_id = conn.execute(text("SELECT plan_id FROM organizations WHERE id = 'org-1'")).scalar_one()
    assert plan_id == "plan_free"

    # Idempotent: re-running against a table that already has the column
    # must not raise or duplicate it.
    _add_organization_plan_id(throwaway)
    assert len([c for c in inspect(throwaway).get_columns("organizations") if c["name"] == "plan_id"]) == 1
