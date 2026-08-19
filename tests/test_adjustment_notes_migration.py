"""Phase 29 -- migration safety.

The promise: adding credit/debit notes is purely additive. No existing
invoice, quote or organization row changes, on a clean database or an
existing one, however many times startup runs.
"""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text

from app.schema_migrations import _add_adjustment_notes


def _engine(tmp_path, name="t.db"):
    return create_engine("sqlite:///" + os.path.join(str(tmp_path), name).replace(os.sep, "/"))


@pytest.fixture
def existing_db(tmp_path):
    """A pre-Phase-29 database with real data in it."""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE organizations ("
                "id CHAR(36) PRIMARY KEY, name VARCHAR(255), "
                "next_invoice_number INTEGER NOT NULL DEFAULT 1, "
                "next_quote_number INTEGER NOT NULL DEFAULT 1)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE invoices (id CHAR(36) PRIMARY KEY, organization_id CHAR(36), "
                "subtotal NUMERIC(14,2), tax_amount NUMERIC(14,2), total NUMERIC(14,2))"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE invoice_line_items (id CHAR(36) PRIMARY KEY, invoice_id CHAR(36), "
                "line_total NUMERIC(14,2), tax_rate NUMERIC(5,4))"
            )
        )
        conn.execute(text("INSERT INTO organizations VALUES ('o1','Acme',7,3)"))
        conn.execute(text("INSERT INTO invoices VALUES ('i1','o1','1700.00','270.00','1970.00')"))
        conn.execute(text("INSERT INTO invoice_line_items VALUES ('l1','i1','1000.00','0.22')"))
    return engine


def _snapshot(engine):
    with engine.begin() as conn:
        return {
            "organizations": conn.execute(
                text("SELECT id, name, next_invoice_number, next_quote_number FROM organizations")
            ).all(),
            "invoices": conn.execute(
                text("SELECT id, subtotal, tax_amount, total FROM invoices")
            ).all(),
            "lines": conn.execute(
                text("SELECT id, line_total, tax_rate FROM invoice_line_items")
            ).all(),
        }


def test_migration_on_a_clean_database(tmp_path):
    engine = _engine(tmp_path, "clean.db")
    _add_adjustment_notes(engine)  # nothing exists yet -- must not raise
    tables = set(inspect(engine).get_table_names())
    # With no organizations table there is nothing to alter, and the note
    # tables are created regardless.
    assert "adjustment_notes" in tables
    assert "adjustment_note_line_items" in tables


def test_migration_changes_no_existing_data(existing_db):
    before = _snapshot(existing_db)
    _add_adjustment_notes(existing_db)
    after = _snapshot(existing_db)
    assert after == before


def test_migration_adds_the_counters_starting_at_one(existing_db):
    _add_adjustment_notes(existing_db)
    with existing_db.begin() as conn:
        row = conn.execute(
            text("SELECT next_credit_note_number, next_debit_note_number FROM organizations")
        ).one()
    assert row == (1, 1)


def test_migration_preserves_the_existing_invoice_sequence(existing_db):
    """The new counters must not disturb the ones already in use."""
    _add_adjustment_notes(existing_db)
    with existing_db.begin() as conn:
        row = conn.execute(
            text("SELECT next_invoice_number, next_quote_number FROM organizations")
        ).one()
    assert row == (7, 3)


def test_migration_is_idempotent(existing_db):
    _add_adjustment_notes(existing_db)
    once = _snapshot(existing_db)
    for _ in range(3):
        _add_adjustment_notes(existing_db)  # repeated startups
    assert _snapshot(existing_db) == once


def test_note_tables_have_the_expected_shape(existing_db):
    _add_adjustment_notes(existing_db)
    insp = inspect(existing_db)
    note_cols = {c["name"] for c in insp.get_columns("adjustment_notes")}
    for expected in (
        "id", "organization_id", "source_invoice_id", "customer_id", "note_type",
        "note_number", "status", "reason", "issue_date", "subtotal", "tax_amount",
        "total", "currency_code", "issued_at", "voided_at",
    ):
        assert expected in note_cols, expected

    line_cols = {c["name"] for c in insp.get_columns("adjustment_note_line_items")}
    for expected in (
        "id", "note_id", "description", "quantity", "unit_price", "line_total",
        "tax_rate", "source_invoice_line_item_id",
    ):
        assert expected in line_cols, expected


def test_per_type_uniqueness_allows_the_same_number_for_each_type(existing_db):
    """CN-000001 and DN-000001 must be able to coexist in one org."""
    _add_adjustment_notes(existing_db)
    with existing_db.begin() as conn:
        for note_type in ("credit", "debit"):
            conn.execute(
                text(
                    "INSERT INTO adjustment_notes (id, organization_id, source_invoice_id, "
                    "note_type, note_number, status, subtotal, tax_amount, total) "
                    f"VALUES ('n-{note_type}', 'o1', 'i1', '{note_type}', 1, 'issued', 0, 0, 0)"
                )
            )
        count = conn.execute(text("SELECT count(*) FROM adjustment_notes")).scalar()
    assert count == 2
