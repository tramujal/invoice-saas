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
