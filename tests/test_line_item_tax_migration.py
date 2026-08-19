"""Phase 28 -- the migration's core promise, tested against a real
database rather than argued for in a comment:

    NO EXISTING DOCUMENT'S SUBTOTAL, TAX OR TOTAL MAY CHANGE.

The test builds a pre-Phase-28 schema (line-item tables with no tax_rate
column), fills it with documents at a spread of rates, records every
stored total, runs the real migration, and compares.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app.schema_migrations import _add_line_item_tax_rates

# (subtotal, rate) pairs covering the ordinary rates plus values whose
# recovered rate is not exactly representable at 4dp.
HISTORICAL = [
    ("1000.00", "0.22"),
    ("1000.00", "0.10"),
    ("1000.00", "0.00"),
    ("83.32", "0.22"),
    ("7.77", "0.10"),
    ("123456.78", "0.22"),
    ("0.01", "0.22"),
    ("0.00", "0.00"),
]


def _legacy_schema(conn) -> None:
    """Just enough of the pre-Phase-28 shape for this migration to run --
    the columns it actually reads and writes, nothing more."""
    conn.execute(
        text(
            "CREATE TABLE invoices (id CHAR(36) PRIMARY KEY, "
            "subtotal NUMERIC(14,2), tax_amount NUMERIC(14,2), total NUMERIC(14,2))"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE invoice_line_items (id CHAR(36) PRIMARY KEY, "
            "invoice_id CHAR(36), line_total NUMERIC(14,2))"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE quotes (id CHAR(36) PRIMARY KEY, tax_rate NUMERIC(5,4), "
            "subtotal NUMERIC(14,2), tax_amount NUMERIC(14,2), total NUMERIC(14,2))"
        )
    )
    conn.execute(
        text(
            "CREATE TABLE quote_line_items (id CHAR(36) PRIMARY KEY, "
            "quote_id CHAR(36), line_total NUMERIC(14,2))"
        )
    )


@pytest.fixture
def legacy_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        _legacy_schema(conn)
        for i, (subtotal, rate) in enumerate(HISTORICAL):
            sub = Decimal(subtotal)
            tax = (sub * Decimal(rate)).quantize(Decimal("0.01"))
            total = sub + tax
            conn.execute(
                text(
                    "INSERT INTO invoices VALUES (:id, :s, :t, :tot)"
                ),
                {"id": f"inv-{i}", "s": str(sub), "t": str(tax), "tot": str(total)},
            )
            # Two lines splitting the subtotal, so grouping has something
            # real to aggregate rather than a single trivial row.
            half = (sub / 2).quantize(Decimal("0.01"))
            conn.execute(
                text("INSERT INTO invoice_line_items VALUES (:id, :inv, :lt)"),
                {"id": f"il-{i}-a", "inv": f"inv-{i}", "lt": str(half)},
            )
            conn.execute(
                text("INSERT INTO invoice_line_items VALUES (:id, :inv, :lt)"),
                {"id": f"il-{i}-b", "inv": f"inv-{i}", "lt": str(sub - half)},
            )
            conn.execute(
                text("INSERT INTO quotes VALUES (:id, :r, :s, :t, :tot)"),
                {"id": f"q-{i}", "r": str(Decimal(rate)), "s": str(sub), "t": str(tax), "tot": str(total)},
            )
            conn.execute(
                text("INSERT INTO quote_line_items VALUES (:id, :q, :lt)"),
                {"id": f"ql-{i}", "q": f"q-{i}", "lt": str(sub)},
            )
    return engine


def _snapshot(engine, table):
    with engine.begin() as conn:
        return {
            row[0]: (row[1], row[2], row[3])
            for row in conn.execute(text(f"SELECT id, subtotal, tax_amount, total FROM {table}"))
        }


def test_migration_changes_no_stored_total(legacy_engine):
    before_invoices = _snapshot(legacy_engine, "invoices")
    before_quotes = _snapshot(legacy_engine, "quotes")

    _add_line_item_tax_rates(legacy_engine)

    assert _snapshot(legacy_engine, "invoices") == before_invoices
    assert _snapshot(legacy_engine, "quotes") == before_quotes


def test_migration_adds_the_column_to_both_tables(legacy_engine):
    _add_line_item_tax_rates(legacy_engine)
    with legacy_engine.begin() as conn:
        for table in ("invoice_line_items", "quote_line_items"):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            assert "tax_rate" in cols


def test_quote_lines_inherit_the_parent_quote_rate_exactly(legacy_engine):
    _add_line_item_tax_rates(legacy_engine)
    with legacy_engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT q.tax_rate, l.tax_rate FROM quote_line_items l "
                "JOIN quotes q ON q.id = l.quote_id"
            )
        ).all()
    assert rows and all(Decimal(str(a)) == Decimal(str(b)) for a, b in rows)


def test_backfilled_invoice_rates_reproduce_the_stored_tax(legacy_engine):
    """The real guarantee: after migration, recomputing an untouched
    historical invoice from its line rates yields the tax it already
    stores."""
    _add_line_item_tax_rates(legacy_engine)
    with legacy_engine.begin() as conn:
        invoices = conn.execute(text("SELECT id, subtotal, tax_amount FROM invoices")).all()
        for invoice_id, subtotal, stored_tax in invoices:
            lines = conn.execute(
                text("SELECT line_total, tax_rate FROM invoice_line_items WHERE invoice_id = :i"),
                {"i": invoice_id},
            ).all()
            # One rate group per invoice here, so this mirrors
            # compute_invoice_totals' grouped arithmetic exactly.
            base = sum(Decimal(str(lt)) for lt, _ in lines)
            rate = Decimal(str(lines[0][1]))
            recomputed = (base * rate).quantize(Decimal("0.01"))
            assert recomputed == Decimal(str(stored_tax)), invoice_id
            assert base == Decimal(str(subtotal))


def test_migration_is_idempotent(legacy_engine):
    _add_line_item_tax_rates(legacy_engine)
    before = _snapshot(legacy_engine, "invoices")
    _add_line_item_tax_rates(legacy_engine)  # must be a no-op, not an error
    assert _snapshot(legacy_engine, "invoices") == before


def test_migration_skips_cleanly_when_tables_are_absent(tmp_path):
    empty = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    _add_line_item_tax_rates(empty)  # must not raise
