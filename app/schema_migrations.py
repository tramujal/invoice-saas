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
