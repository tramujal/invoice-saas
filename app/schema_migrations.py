"""Lightweight, idempotent startup migrations.

This project doesn't use Alembic. Base.metadata.create_all() (called from
init_db()) handles brand-new databases correctly, but it never alters an
existing table. For schema changes that touch tables which may already have
data, add a small guarded step here: check whether the change is already
applied, and if not, apply it with plain SQL that works on both SQLite and
Postgres. Safe to call on every startup.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def run_startup_migrations(engine: Engine) -> None:
    _add_invoice_numbering(engine)
    _add_organization_profile_fields(engine)
    _add_organization_localization_fields(engine)
    _add_password_reset_tokens_table(engine)
    _add_invoice_currency_and_language(engine)
    _add_user_email_verified_at(engine)
    _add_email_verification_tokens_table(engine)
    _add_customer_tax_id(engine)
    _add_assistant_actions_table(engine)
    _add_invoice_due_date(engine)
    _add_organization_timezone_and_reminders(engine)
    _add_invoice_reminders_table(engine)
    _add_due_date_and_status_indexes(engine)
    _add_products_table(engine)
    _add_invoice_line_item_product_id(engine)
    _add_organization_quote_fields(engine)
    _add_quotes_table(engine)
    _add_quote_line_items_table(engine)
    _add_quote_reminders_table(engine)
    _add_organization_member_role_fields(engine)
    _add_organization_invitations_table(engine)
    _add_user_platform_role(engine)
    _add_organization_status(engine)
    _add_platform_audit_log_table(engine)
    _add_user_status(engine)
    _add_platform_audit_log_user_target_and_details(engine)
    _add_platform_audit_log_query_indexes(engine)
    _add_platform_settings_table(engine)
    _add_platform_settings_version(engine)
    _add_plans_table(engine)
    _seed_default_plans(engine)
    _add_organization_plan_id(engine)


def _add_invoice_numbering(engine: Engine) -> None:
    inspector = inspect(engine)
    if "invoices" not in inspector.get_table_names():
        return

    org_columns = {c["name"] for c in inspector.get_columns("organizations")}
    invoice_columns = {c["name"] for c in inspector.get_columns("invoices")}

    needs_org_column = "next_invoice_number" not in org_columns
    needs_invoice_column = "invoice_number" not in invoice_columns
    if not needs_org_column and not needs_invoice_column:
        return

    with engine.begin() as conn:
        if needs_org_column:
            conn.execute(
                text(
                    "ALTER TABLE organizations "
                    "ADD COLUMN next_invoice_number INTEGER NOT NULL DEFAULT 1"
                )
            )

        if needs_invoice_column:
            conn.execute(
                text(
                    "ALTER TABLE invoices "
                    "ADD COLUMN invoice_number INTEGER NOT NULL DEFAULT 0"
                )
            )
            _backfill_invoice_numbers(conn)
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_invoices_org_invoice_number "
                    "ON invoices (organization_id, invoice_number)"
                )
            )


def _add_organization_profile_fields(engine: Engine) -> None:
    """Adds the optional business-profile columns to organizations.

    All nullable, so existing rows (and the invoices that reference them)
    stay valid with no backfill.
    """
    inspector = inspect(engine)
    if "organizations" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("organizations")}
    new_columns = {
        "business_name": "VARCHAR(255)",
        "tax_id": "VARCHAR(64)",
        "address": "VARCHAR(512)",
        "phone": "VARCHAR(64)",
        "email": "VARCHAR(255)",
        "logo_url": "VARCHAR(1024)",
    }
    missing = {name: t for name, t in new_columns.items() if name not in columns}
    if not missing:
        return

    with engine.begin() as conn:
        for name, coltype in missing.items():
            conn.execute(text(f"ALTER TABLE organizations ADD COLUMN {name} {coltype}"))


def _add_organization_localization_fields(engine: Engine) -> None:
    """Adds language/currency_code/tax_label to organizations.

    NOT NULL with DB-level defaults, so existing rows are immediately valid
    with the documented safe fallbacks — no backfill needed.
    """
    inspector = inspect(engine)
    if "organizations" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("organizations")}
    new_columns = {
        "language": "VARCHAR(8) NOT NULL DEFAULT 'en'",
        "currency_code": "VARCHAR(8) NOT NULL DEFAULT 'USD'",
        "tax_label": "VARCHAR(32) NOT NULL DEFAULT 'Tax ID'",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in columns}
    if not missing:
        return

    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE organizations ADD COLUMN {name} {ddl}"))


def _add_password_reset_tokens_table(engine: Engine) -> None:
    """Creates password_reset_tokens if it's missing.

    Base.metadata.create_all() (called before this function, from init_db())
    already creates this table on any database that doesn't have it yet,
    since PasswordResetToken is a declared model — this guarded step is an
    explicit, idempotent safety net matching this file's established
    pattern for every other schema change, in case create_all is ever
    skipped for a given deployment path.
    """
    inspector = inspect(engine)
    if "password_reset_tokens" in inspector.get_table_names():
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS password_reset_tokens ("
                "id CHAR(36) PRIMARY KEY, "
                "user_id CHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "token_hash VARCHAR(64) NOT NULL UNIQUE, "
                "expires_at TIMESTAMP NOT NULL, "
                "used_at TIMESTAMP NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )


def _add_invoice_currency_and_language(engine: Engine) -> None:
    """Adds currency_code/language to invoices, backfilled from each
    invoice's organization's CURRENT currency/language at migration time.

    SQLite has no ALTER COLUMN ... SET NOT NULL, so (matching
    _add_invoice_numbering's approach for invoice_number) each column is
    added NOT NULL with a placeholder default and immediately backfilled
    with real values in the same transaction — the column is never
    nullable, but its initial values get corrected before any other code
    can observe them.

    From this migration onward, organization currency_code/language
    changes only affect *new* invoices (set explicitly at creation, see
    create_invoice) — every existing invoice keeps whatever it's
    backfilled with here, permanently.
    """
    inspector = inspect(engine)
    if "invoices" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("invoices")}
    needs_currency = "currency_code" not in columns
    needs_language = "language" not in columns
    if not needs_currency and not needs_language:
        return

    with engine.begin() as conn:
        if needs_currency:
            conn.execute(
                text(
                    "ALTER TABLE invoices "
                    "ADD COLUMN currency_code VARCHAR(8) NOT NULL DEFAULT 'USD'"
                )
            )
            conn.execute(
                text(
                    "UPDATE invoices SET currency_code = ("
                    "SELECT currency_code FROM organizations "
                    "WHERE organizations.id = invoices.organization_id"
                    ") WHERE EXISTS ("
                    "SELECT 1 FROM organizations "
                    "WHERE organizations.id = invoices.organization_id"
                    ")"
                )
            )
        if needs_language:
            conn.execute(
                text(
                    "ALTER TABLE invoices "
                    "ADD COLUMN language VARCHAR(8) NOT NULL DEFAULT 'en'"
                )
            )
            conn.execute(
                text(
                    "UPDATE invoices SET language = ("
                    "SELECT language FROM organizations "
                    "WHERE organizations.id = invoices.organization_id"
                    ") WHERE EXISTS ("
                    "SELECT 1 FROM organizations "
                    "WHERE organizations.id = invoices.organization_id"
                    ")"
                )
            )


def _add_user_email_verified_at(engine: Engine) -> None:
    """Adds users.email_verified_at (nullable — no backfill needed for the
    column itself to be valid).

    However every user row that already exists at migration time is
    explicitly backfilled to "verified" (email_verified_at = now), rather
    than left NULL: these accounts never went through this flow and have no
    way to retroactively receive or click a verification link, so treating
    them as unverified would instantly lock every current user (including
    the seeded demo account, whose email address isn't real) out of
    creating invoices/customers or sending email, with no self-serve way to
    fix it. Only users created from this point forward go through real
    verification.
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("users")}
    if "email_verified_at" in columns:
        return

    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP NULL")
        )
        conn.execute(
            text("UPDATE users SET email_verified_at = CURRENT_TIMESTAMP")
        )


def _add_email_verification_tokens_table(engine: Engine) -> None:
    """Creates email_verification_tokens if it's missing — same idempotent
    safety net as _add_password_reset_tokens_table, for the same reason
    (Base.metadata.create_all() already creates this table on a fresh
    database since EmailVerificationToken is a declared model)."""
    inspector = inspect(engine)
    if "email_verification_tokens" in inspector.get_table_names():
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS email_verification_tokens ("
                "id CHAR(36) PRIMARY KEY, "
                "user_id CHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "token_hash VARCHAR(64) NOT NULL UNIQUE, "
                "expires_at TIMESTAMP NOT NULL, "
                "used_at TIMESTAMP NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )


def _add_customer_tax_id(engine: Engine) -> None:
    """Adds customers.tax_id, defaulted to '' for existing rows (matching
    phone/address's existing nullable-in-spirit-but-NOT-NULL-with-default
    pattern) — no backfill of real values is possible or needed, an empty
    string means "not provided," identical to how phone/address already
    behave when left blank.
    """
    inspector = inspect(engine)
    if "customers" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("customers")}
    if "tax_id" in columns:
        return

    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE customers ADD COLUMN tax_id VARCHAR(64) NOT NULL DEFAULT ''")
        )


def _add_assistant_actions_table(engine: Engine) -> None:
    """Creates assistant_actions if it's missing — same idempotent safety
    net as _add_password_reset_tokens_table/_add_email_verification_tokens_table,
    for the same reason (Base.metadata.create_all() already creates this
    table on a fresh database since AssistantAction is a declared model)."""
    inspector = inspect(engine)
    if "assistant_actions" in inspector.get_table_names():
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS assistant_actions ("
                "id CHAR(36) PRIMARY KEY, "
                "organization_id CHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
                "user_id CHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "action_name VARCHAR(64) NOT NULL, "
                "input_payload TEXT NOT NULL, "
                "summary TEXT NOT NULL, "
                "status VARCHAR(16) NOT NULL DEFAULT 'proposed', "
                "failure_code VARCHAR(64) NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "expires_at TIMESTAMP NOT NULL, "
                "executed_at TIMESTAMP NULL"
                ")"
            )
        )


def _add_invoice_due_date(engine: Engine) -> None:
    """Adds invoices.due_date, nullable, no backfill -- per the plan, a NULL
    due_date is what keeps historical invoices' displayed status frozen
    exactly as it was (see app/effective_status.py)."""
    inspector = inspect(engine)
    if "invoices" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("invoices")}
    if "due_date" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE invoices ADD COLUMN due_date DATE NULL"))


def _add_organization_timezone_and_reminders(engine: Engine) -> None:
    """Adds Organization.timezone + the 4 reminder-settings columns, each
    with a safe default so every existing organization keeps working
    unchanged (reminders_enabled defaults to FALSE -- opt-in only)."""
    inspector = inspect(engine)
    if "organizations" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    new_columns = {
        "timezone": "VARCHAR(64) NOT NULL DEFAULT 'UTC'",
        "reminders_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        "reminder_before_due_days": "VARCHAR(64) NOT NULL DEFAULT '3'",
        "reminder_on_due_date": "BOOLEAN NOT NULL DEFAULT TRUE",
        "reminder_after_due_days": "VARCHAR(64) NOT NULL DEFAULT '7'",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in columns}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE organizations ADD COLUMN {name} {ddl}"))


def _add_invoice_reminders_table(engine: Engine) -> None:
    """Creates invoice_reminders if it's missing -- same idempotent safety
    net as _add_assistant_actions_table. The unique constraint is the sole
    idempotency/concurrency guarantee for scheduled, manual, and AI-agent
    reminder sends (see app/models.py InvoiceReminder)."""
    inspector = inspect(engine)
    if "invoice_reminders" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS invoice_reminders ("
                "id CHAR(36) PRIMARY KEY, "
                "organization_id CHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
                "invoice_id CHAR(36) NOT NULL REFERENCES invoices(id) ON DELETE CASCADE, "
                "reminder_type VARCHAR(16) NOT NULL, "
                "days_offset INTEGER NULL, "
                "scheduled_for_date DATE NOT NULL, "
                "recipient_email VARCHAR(255) NOT NULL, "
                "status VARCHAR(16) NOT NULL DEFAULT 'pending', "
                "attempt_count INTEGER NOT NULL DEFAULT 0, "
                "triggered_by VARCHAR(16) NOT NULL, "
                "provider_message_id VARCHAR(255) NULL, "
                "failure_code VARCHAR(64) NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "sent_at TIMESTAMP NULL, "
                "CONSTRAINT uq_invoice_reminder_idempotency "
                "UNIQUE (invoice_id, reminder_type, scheduled_for_date)"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_invoice_reminders_org_status "
                "ON invoice_reminders (organization_id, status)"
            )
        )


def _add_due_date_and_status_indexes(engine: Engine) -> None:
    """Idempotent indexes backing the reminder job's and insights' bounded
    queries on due_date/payment_status -- never a full-table scan."""
    inspector = inspect(engine)
    if "invoices" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_invoices_due_date ON invoices (due_date)")
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_invoices_payment_status "
                "ON invoices (payment_status)"
            )
        )


def _add_products_table(engine: Engine) -> None:
    """Creates products if it's missing -- same idempotent safety net as
    _add_assistant_actions_table/_add_invoice_reminders_table (Base.metadata.
    create_all() already creates this table on a fresh database since
    Product is a declared model)."""
    inspector = inspect(engine)
    if "products" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS products ("
                "id CHAR(36) PRIMARY KEY, "
                "organization_id CHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
                "name VARCHAR(255) NOT NULL, "
                "description VARCHAR(1024) NOT NULL DEFAULT '', "
                "type VARCHAR(16) NOT NULL DEFAULT 'service', "
                "sku VARCHAR(64) NOT NULL DEFAULT '', "
                "default_unit_price NUMERIC(14, 2) NOT NULL DEFAULT 0, "
                "currency_code VARCHAR(8) NOT NULL DEFAULT 'USD', "
                "default_tax_rate NUMERIC(5, 4) NOT NULL DEFAULT 0, "
                "active BOOLEAN NOT NULL DEFAULT TRUE, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_products_org_active "
                "ON products (organization_id, active)"
            )
        )


def _add_invoice_line_item_product_id(engine: Engine) -> None:
    """Adds invoice_line_items.product_id, nullable -- a pure analytics
    tag (see InvoiceLineItem.product_id's docstring in app/models.py),
    never read back to reconstruct a line's snapshot values. Requires the
    products table to already exist (see run_startup_migrations' call
    order: _add_products_table always runs first)."""
    inspector = inspect(engine)
    if "invoice_line_items" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("invoice_line_items")}
    if "product_id" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE invoice_line_items ADD COLUMN product_id CHAR(36) "
                "NULL REFERENCES products(id) ON DELETE SET NULL"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_invoice_line_items_product_id "
                "ON invoice_line_items (product_id)"
            )
        )


def _add_organization_quote_fields(engine: Engine) -> None:
    """Adds next_quote_number/quote_reminders_enabled/
    quote_reminder_before_expiry_days to organizations -- each with a safe
    default so every existing organization keeps working unchanged
    (quote_reminders_enabled defaults to FALSE, same opt-in-only rationale
    as reminders_enabled)."""
    inspector = inspect(engine)
    if "organizations" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    new_columns = {
        "next_quote_number": "INTEGER NOT NULL DEFAULT 1",
        "quote_reminders_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        "quote_reminder_before_expiry_days": "VARCHAR(64) NOT NULL DEFAULT '3'",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in columns}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE organizations ADD COLUMN {name} {ddl}"))


def _add_quotes_table(engine: Engine) -> None:
    """Creates quotes if it's missing -- same idempotent safety net as
    _add_products_table/_add_invoice_reminders_table (Base.metadata.
    create_all() already creates this table on a fresh database since
    Quote is a declared model)."""
    inspector = inspect(engine)
    if "quotes" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS quotes ("
                "id CHAR(36) PRIMARY KEY, "
                "organization_id CHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
                "quote_number INTEGER NOT NULL, "
                "created_by_user_id CHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL, "
                "customer_id CHAR(36) NULL REFERENCES customers(id) ON DELETE SET NULL, "
                "subtotal NUMERIC(14, 2) NOT NULL, "
                "tax_rate NUMERIC(5, 4) NOT NULL DEFAULT 0, "
                "tax_amount NUMERIC(14, 2) NOT NULL, "
                "total NUMERIC(14, 2) NOT NULL, "
                "status VARCHAR(16) NOT NULL DEFAULT 'draft', "
                "currency_code VARCHAR(8) NOT NULL DEFAULT 'USD', "
                "language VARCHAR(8) NOT NULL DEFAULT 'en', "
                "issue_date DATE NOT NULL, "
                "expiry_date DATE NULL, "
                "notes TEXT NOT NULL DEFAULT '', "
                "active BOOLEAN NOT NULL DEFAULT TRUE, "
                "public_token VARCHAR(64) NOT NULL UNIQUE, "
                "converted_invoice_id CHAR(36) NULL REFERENCES invoices(id) ON DELETE SET NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "CONSTRAINT uq_quote_org_number UNIQUE (organization_id, quote_number)"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_quotes_org_status "
                "ON quotes (organization_id, status)"
            )
        )


def _add_quote_line_items_table(engine: Engine) -> None:
    """Creates quote_line_items if it's missing -- requires the quotes and
    products tables to already exist (see run_startup_migrations' call
    order: _add_quotes_table and _add_products_table always run first)."""
    inspector = inspect(engine)
    if "quote_line_items" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS quote_line_items ("
                "id CHAR(36) PRIMARY KEY, "
                "quote_id CHAR(36) NOT NULL REFERENCES quotes(id) ON DELETE CASCADE, "
                "description VARCHAR(512) NOT NULL, "
                "quantity NUMERIC(14, 4) NOT NULL, "
                "unit_price NUMERIC(14, 2) NOT NULL, "
                "line_total NUMERIC(14, 2) NOT NULL, "
                "product_id CHAR(36) NULL REFERENCES products(id) ON DELETE SET NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_quote_line_items_product_id "
                "ON quote_line_items (product_id)"
            )
        )


def _add_quote_reminders_table(engine: Engine) -> None:
    """Creates quote_reminders if it's missing -- same idempotent safety
    net as _add_invoice_reminders_table. The unique constraint is the sole
    idempotency/concurrency guarantee for scheduled quote-expiry reminder
    sends (see app/models.py QuoteReminder)."""
    inspector = inspect(engine)
    if "quote_reminders" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS quote_reminders ("
                "id CHAR(36) PRIMARY KEY, "
                "organization_id CHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
                "quote_id CHAR(36) NOT NULL REFERENCES quotes(id) ON DELETE CASCADE, "
                "days_offset INTEGER NULL, "
                "scheduled_for_date DATE NOT NULL, "
                "recipient_email VARCHAR(255) NOT NULL, "
                "status VARCHAR(16) NOT NULL DEFAULT 'pending', "
                "attempt_count INTEGER NOT NULL DEFAULT 0, "
                "triggered_by VARCHAR(16) NOT NULL, "
                "failure_code VARCHAR(64) NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "sent_at TIMESTAMP NULL, "
                "CONSTRAINT uq_quote_reminder_idempotency "
                "UNIQUE (quote_id, scheduled_for_date)"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_quote_reminders_org_status "
                "ON quote_reminders (organization_id, status)"
            )
        )


def _add_organization_member_role_fields(engine: Engine) -> None:
    """Adds role/status/invited_by/invited_at/accepted_at/role_changed_by/
    removed_by/created_at/updated_at to organization_members.

    role's backfill is unambiguous: today, app.routers.auth.register() is
    the ONLY code path that ever creates an organization_members row (no
    invite path has existed until this feature), so every existing
    organization has exactly one member -- who is, by construction,
    unambiguously its owner. Every pre-existing row is therefore backfilled
    to role='owner', status='active', with accepted_at/created_at/
    updated_at all backfilled to CURRENT_TIMESTAMP (there is no earlier,
    real timestamp to recover, since this table had none before now).
    """
    inspector = inspect(engine)
    if "organization_members" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("organization_members")}
    new_columns = {
        "role": "VARCHAR(16) NOT NULL DEFAULT 'member'",
        "status": "VARCHAR(16) NOT NULL DEFAULT 'active'",
        "invited_by": "CHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL",
        "invited_at": "TIMESTAMP NULL",
        "accepted_at": "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP",
        "role_changed_by": "CHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL",
        "removed_by": "CHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL",
        "created_at": "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in columns}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE organization_members ADD COLUMN {name} {ddl}"))
        if "role" in missing:
            conn.execute(text("UPDATE organization_members SET role = 'owner'"))
        if "accepted_at" in missing:
            conn.execute(
                text("UPDATE organization_members SET accepted_at = CURRENT_TIMESTAMP")
            )
        if "created_at" in missing:
            conn.execute(
                text("UPDATE organization_members SET created_at = CURRENT_TIMESTAMP")
            )
        if "updated_at" in missing:
            conn.execute(
                text("UPDATE organization_members SET updated_at = CURRENT_TIMESTAMP")
            )


def _add_organization_invitations_table(engine: Engine) -> None:
    """Creates organization_invitations if it's missing -- same idempotent
    safety net as _add_quotes_table/_add_invoice_reminders_table
    (Base.metadata.create_all() already creates this table on a fresh
    database since OrganizationInvitation is a declared model)."""
    inspector = inspect(engine)
    if "organization_invitations" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS organization_invitations ("
                "id CHAR(36) PRIMARY KEY, "
                "organization_id CHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, "
                "email VARCHAR(255) NOT NULL, "
                "role VARCHAR(16) NOT NULL, "
                "token_hash VARCHAR(64) NOT NULL UNIQUE, "
                "expires_at TIMESTAMP NOT NULL, "
                "accepted_at TIMESTAMP NULL, "
                "created_by CHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_org_invitations_org_email "
                "ON organization_invitations (organization_id, email)"
            )
        )


def _add_user_platform_role(engine: Engine) -> None:
    """Adds User.platform_role -- a nullable column backing the
    platform-administration authorization axis, entirely independent from
    OrganizationMember.role/organization membership. NULL means "not a
    platform admin". See app.platform_permissions for the role/permission
    map and app.scripts.grant_platform_role for how the first platform
    admin is bootstrapped (never through the ordinary signup/API surface).
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "platform_role" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN platform_role VARCHAR(32)"))


def _add_organization_status(engine: Engine) -> None:
    """Adds Organization.status -- the DEFAULT clause backfills every
    existing row to 'active' atomically as part of the ALTER TABLE itself
    (same proven pattern as _add_organization_localization_fields), so no
    separate backfill step is needed."""
    inspector = inspect(engine)
    if "organizations" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    if "status" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE organizations ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active'"))


def _add_platform_audit_log_table(engine: Engine) -> None:
    """Creates platform_audit_log if it's missing -- same idempotent
    safety net as _add_organization_invitations_table (Base.metadata.
    create_all() already creates this table on a fresh database since
    PlatformAuditLog is a declared model). Append-only: no migration here
    ever alters or removes a row, and no route exposes update/delete."""
    inspector = inspect(engine)
    if "platform_audit_log" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS platform_audit_log ("
                "id CHAR(36) PRIMARY KEY, "
                "actor_user_id CHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL, "
                "actor_email VARCHAR(255) NOT NULL, "
                "action VARCHAR(64) NOT NULL, "
                "target_organization_id CHAR(36) NULL REFERENCES organizations(id) ON DELETE SET NULL, "
                "target_organization_name VARCHAR(255) NOT NULL, "
                "reason TEXT NOT NULL, "
                "client_ip VARCHAR(64) NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_platform_audit_log_target_org "
                "ON platform_audit_log (target_organization_id)"
            )
        )


def _add_user_status(engine: Engine) -> None:
    """Adds User.status -- the DEFAULT clause backfills every existing
    row to 'active' atomically as part of the ALTER TABLE itself, same
    proven pattern as _add_organization_status."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "status" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active'"))


def _add_platform_audit_log_user_target_and_details(engine: Engine) -> None:
    """Adds target_user_id/target_user_email/details to platform_audit_log
    -- all nullable, so this is a pure additive change with no backfill
    needed (every existing row is an organization-targeted action, which
    correctly leaves these three new columns NULL)."""
    inspector = inspect(engine)
    if "platform_audit_log" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("platform_audit_log")}
    new_columns = {
        "target_user_id": "CHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL",
        "target_user_email": "VARCHAR(255) NULL",
        "details": "TEXT NULL",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in columns}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE platform_audit_log ADD COLUMN {name} {ddl}"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_platform_audit_log_target_user "
                "ON platform_audit_log (target_user_id)"
            )
        )


def _add_platform_audit_log_query_indexes(engine: Engine) -> None:
    """Adds the indexes Phase 13F's filterable/sortable audit-log listing
    needs -- created_at (the default sort key), action, and actor_user_id
    (all frequently filtered/ordered on) -- target_organization_id/
    target_user_id already have their own indexes from earlier phases.
    CREATE INDEX IF NOT EXISTS is itself idempotent, so this needs no
    inspector column/table check first, unlike every ALTER TABLE
    migration in this file."""
    inspector = inspect(engine)
    if "platform_audit_log" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_platform_audit_log_created_at ON platform_audit_log (created_at)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_platform_audit_log_action ON platform_audit_log (action)")
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_platform_audit_log_actor_user_id "
                "ON platform_audit_log (actor_user_id)"
            )
        )


def _add_platform_settings_table(engine: Engine) -> None:
    """Creates platform_settings if it's missing -- same idempotent safety
    net as _add_platform_audit_log_table (Base.metadata.create_all()
    already creates this table on a fresh database since PlatformSettings
    is a declared model). No row is ever inserted here -- the singleton
    row is lazily created on first read with code-defined defaults (see
    app.services.platform_settings.get_or_create_settings_row), which is
    what "deterministic defaults when the row does not yet exist" means
    in practice."""
    inspector = inspect(engine)
    if "platform_settings" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS platform_settings ("
                "id CHAR(36) PRIMARY KEY, "
                "maintenance_mode BOOLEAN NOT NULL DEFAULT FALSE, "
                "registrations_enabled BOOLEAN NOT NULL DEFAULT TRUE, "
                "ai_enabled BOOLEAN NOT NULL DEFAULT TRUE, "
                "emails_enabled BOOLEAN NOT NULL DEFAULT TRUE, "
                "invoice_reminders_enabled BOOLEAN NOT NULL DEFAULT TRUE, "
                "quote_reminders_enabled BOOLEAN NOT NULL DEFAULT TRUE, "
                "default_language VARCHAR(8) NOT NULL DEFAULT 'en', "
                "default_currency VARCHAR(8) NOT NULL DEFAULT 'USD', "
                "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_by_user_id CHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL, "
                "version INTEGER NOT NULL DEFAULT 1"
                ")"
            )
        )


def _add_platform_settings_version(engine: Engine) -> None:
    """Adds PlatformSettings.version -- the optimistic-concurrency token
    PATCH /admin/settings uses to detect two admins editing at once (see
    that endpoint's own docstring). The DEFAULT clause backfills any
    pre-existing singleton row to version 1 atomically as part of the
    ALTER TABLE itself, same proven pattern as _add_user_status."""
    inspector = inspect(engine)
    if "platform_settings" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("platform_settings")}
    if "version" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE platform_settings ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))


def _add_plans_table(engine: Engine) -> None:
    """Creates plans if it's missing -- same idempotent safety net as
    _add_platform_settings_table (Base.metadata.create_all() already
    creates this table on a fresh database since Plan is a declared
    model). Seeding the four built-in rows is a separate step
    (_seed_default_plans), which must run after this one."""
    inspector = inspect(engine)
    if "plans" in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS plans ("
                "id CHAR(36) PRIMARY KEY, "
                "code VARCHAR(32) NOT NULL UNIQUE, "
                "name VARCHAR(100) NOT NULL, "
                "description VARCHAR(500) NULL, "
                "is_active BOOLEAN NOT NULL DEFAULT TRUE, "
                "is_default BOOLEAN NOT NULL DEFAULT FALSE, "
                "sort_order INTEGER NOT NULL DEFAULT 0, "
                "max_users INTEGER NULL, "
                "max_customers INTEGER NULL, "
                "max_products INTEGER NULL, "
                "max_invoices_per_month INTEGER NULL, "
                "max_quotes_per_month INTEGER NULL, "
                "max_ai_actions_per_month INTEGER NULL, "
                "storage_limit_mb INTEGER NULL, "
                "custom_branding_enabled BOOLEAN NOT NULL DEFAULT FALSE, "
                "api_access_enabled BOOLEAN NOT NULL DEFAULT FALSE, "
                "advanced_reports_enabled BOOLEAN NOT NULL DEFAULT FALSE, "
                "version INTEGER NOT NULL DEFAULT 1, "
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )


# (id, code, name, is_default, max_users, max_customers, max_products,
#  max_invoices_per_month, max_quotes_per_month, max_ai_actions_per_month,
#  storage_limit_mb, custom_branding_enabled, api_access_enabled,
#  advanced_reports_enabled, sort_order)
_DEFAULT_PLAN_SEEDS = [
    ("plan_free", "free", "Free", True, 2, 100, 100, 50, 50, 25, 500, False, False, False, 0),
    ("plan_starter", "starter", "Starter", False, 10, 1000, 1000, 500, 500, 250, 5000, False, False, True, 1),
    ("plan_pro", "pro", "Pro", False, 50, 10000, 10000, 10000, 10000, 5000, 50000, True, True, True, 2),
    (
        "plan_enterprise",
        "enterprise",
        "Enterprise",
        False,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        True,
        True,
        True,
        3,
    ),
]


def _seed_default_plans(engine: Engine) -> None:
    """Inserts the four built-in commercial plans (see the phase's own
    "no billing yet" scope note) by fixed code, one INSERT per plan
    missing by that code -- never touches a plan that already exists, so
    an operator's later edits (via PATCH /admin/plans) are never
    overwritten by a re-run of this migration on the next startup. Plan
    ids are fixed literals (app.models.PLAN_ID_FREE etc.), not generated
    UUIDs, specifically so _add_organization_plan_id below can reference
    "plan_free" as a plain SQL-level DEFAULT for existing organizations
    without a separate backfill step."""
    inspector = inspect(engine)
    if "plans" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        existing_codes = {row[0] for row in conn.execute(text("SELECT code FROM plans")).all()}
        for (
            plan_id,
            code,
            name,
            is_default,
            max_users,
            max_customers,
            max_products,
            max_invoices,
            max_quotes,
            max_ai_actions,
            storage_mb,
            branding,
            api_access,
            advanced_reports,
            sort_order,
        ) in _DEFAULT_PLAN_SEEDS:
            if code in existing_codes:
                continue
            conn.execute(
                text(
                    "INSERT INTO plans ("
                    "id, code, name, is_active, is_default, sort_order, "
                    "max_users, max_customers, max_products, max_invoices_per_month, "
                    "max_quotes_per_month, max_ai_actions_per_month, storage_limit_mb, "
                    "custom_branding_enabled, api_access_enabled, advanced_reports_enabled, version"
                    ") VALUES ("
                    ":id, :code, :name, TRUE, :is_default, :sort_order, "
                    ":max_users, :max_customers, :max_products, :max_invoices, "
                    ":max_quotes, :max_ai_actions, :storage_mb, "
                    ":branding, :api_access, :advanced_reports, 1"
                    ")"
                ),
                {
                    "id": plan_id,
                    "code": code,
                    "name": name,
                    "is_default": is_default,
                    "sort_order": sort_order,
                    "max_users": max_users,
                    "max_customers": max_customers,
                    "max_products": max_products,
                    "max_invoices": max_invoices,
                    "max_quotes": max_quotes,
                    "max_ai_actions": max_ai_actions,
                    "storage_mb": storage_mb,
                    "branding": branding,
                    "api_access": api_access,
                    "advanced_reports": advanced_reports,
                },
            )


def _add_organization_plan_id(engine: Engine) -> None:
    """Adds Organization.plan_id -- every existing organization is
    backfilled to the free plan atomically as part of the ALTER TABLE
    itself (DEFAULT 'plan_free'), the same proven pattern as every other
    NOT-NULL-with-backfill column in this file, made possible here only
    because the seeded free plan has a fixed, known-ahead-of-time id
    (see _seed_default_plans) rather than a randomly generated UUID.
    Must run after _add_plans_table/_seed_default_plans so the
    referenced row already exists.

    SQLite's ALTER TABLE flatly refuses to combine a REFERENCES clause
    with a non-NULL DEFAULT on the same ADD COLUMN ("Cannot add a
    REFERENCES column with non-NULL default value") -- a hard engine
    limitation, not a style choice, so the column is added without the
    inline FK there; the ORM model still declares the FK for any table
    SQLAlchemy creates fresh (create_all(), including the test suite).
    Postgres (production, see docker-compose.yml/render.yaml) supports
    the combined form directly."""
    inspector = inspect(engine)
    if "organizations" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    if "plan_id" in columns:
        return
    references_clause = "" if engine.dialect.name == "sqlite" else " REFERENCES plans(id)"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER TABLE organizations ADD COLUMN plan_id CHAR(36) "
                f"NOT NULL DEFAULT 'plan_free'{references_clause}"
            )
        )


def _backfill_invoice_numbers(conn) -> None:
    """Assigns sequential invoice numbers to pre-existing invoices, per org,
    ordered by creation date, then fast-forwards each org's counter."""
    org_ids = [row[0] for row in conn.execute(text("SELECT id FROM organizations")).all()]
    for org_id in org_ids:
        rows = conn.execute(
            text(
                "SELECT id FROM invoices WHERE organization_id = :org_id "
                "ORDER BY created_at ASC"
            ),
            {"org_id": org_id},
        ).all()

        next_number = 1
        for (invoice_id,) in rows:
            conn.execute(
                text("UPDATE invoices SET invoice_number = :n WHERE id = :id"),
                {"n": next_number, "id": invoice_id},
            )
            next_number += 1

        conn.execute(
            text(
                "UPDATE organizations SET next_invoice_number = :n WHERE id = :org_id"
            ),
            {"n": next_number, "org_id": org_id},
        )
