"""Phase 29 -- over-credit protection under concurrency.

The property: two simultaneous credit notes must never both consume the
same remaining creditable amount.

WHY THIS IS TESTED AGAINST POSTGRES, AND SKIPPED OTHERWISE
----------------------------------------------------------
The protection is `SELECT ... FOR UPDATE` on the source invoice row. That
is a real lock on PostgreSQL and a no-op on SQLite -- SQLite serializes
writers at the file level instead, so a SQLite run would pass this test
for the wrong reason and prove nothing about production. Rather than
assert a guarantee the test environment cannot actually exercise, this
skips unless a real PostgreSQL URL is provided:

    TEST_POSTGRES_URL=postgresql+psycopg://user:pass@localhost/dbname

The deterministic, always-run part of the guarantee (the ceiling is
re-checked at issue time, so a stale draft cannot slip through) lives in
tests/test_adjustment_notes.py::test_the_ceiling_is_rechecked_at_issue_time
and does not depend on the backend.
"""

import os
import threading
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.adjustment_note_type import AdjustmentNoteType
from app.models import Base
from app.schema_migrations import run_startup_migrations
from app.schemas import AdjustmentNoteLineItemCreate
from app.services.adjustment_notes import (
    OverCreditError,
    create_adjustment_note,
    get_invoice_adjustments,
)

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="needs a real PostgreSQL (SELECT ... FOR UPDATE is a no-op on SQLite)",
)


@pytest.fixture
def pg_sessionmaker():
    engine = create_engine(POSTGRES_URL)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Organizations FK-reference a seeded default Plan row -- the app's
    # own startup path (app.models.init_db) always runs this after
    # create_all; this fixture must too, or make_org_with_owner's insert
    # fails on a fresh Postgres database with no migration history.
    run_startup_migrations(engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _seed(Session):
    """A 1000.00 invoice with nothing credited yet."""
    from tests.factories import make_invoice, make_org_with_owner
    from app.schemas import InvoiceLineItemCreate

    db = Session()
    try:
        owner = make_org_with_owner(db, email="conc@example.com", org_name="Concurrency Co")
        invoice = make_invoice(
            db,
            owner.organization,
            owner.user,
            line_items=[
                InvoiceLineItemCreate(
                    description="Item",
                    quantity=Decimal("1"),
                    unit_price=Decimal("1000.00"),
                    tax_rate=Decimal("0"),
                )
            ],
            tax_rate=Decimal("0"),
        )
        db.commit()
        return owner.organization.id, owner.user.id, invoice.id
    finally:
        db.close()


def test_two_concurrent_credit_notes_cannot_both_consume_the_ceiling(pg_sessionmaker):
    """Both threads try to credit the FULL 1000.00 at the same time.
    Exactly one must succeed; the invoice must never end up over-credited.
    """
    org_id, user_id, invoice_id = _seed(pg_sessionmaker)

    barrier = threading.Barrier(2)
    results: list = []

    def attempt():
        db = pg_sessionmaker()
        try:
            user = db.get(__import__("app.models", fromlist=["User"]).User, user_id)
            # Both threads arrive at the locked read together, which is
            # what makes this a genuine race rather than a sequence.
            barrier.wait(timeout=10)
            note = create_adjustment_note(
                db,
                org_id,
                note_type=AdjustmentNoteType.credit,
                source_invoice_id=invoice_id,
                line_items=[
                    AdjustmentNoteLineItemCreate(
                        description="Full credit",
                        quantity=Decimal("1"),
                        unit_price=Decimal("1000.00"),
                        tax_rate=Decimal("0"),
                    )
                ],
                current_user=user,
                issue_immediately=True,
            )
            results.append(("ok", note.total))
        except OverCreditError as exc:
            results.append(("blocked", exc.remaining))
        except Exception as exc:  # surfaced, never swallowed
            results.append(("error", repr(exc)))
        finally:
            db.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    outcomes = [r[0] for r in results]
    assert outcomes.count("ok") == 1, results
    assert outcomes.count("blocked") == 1, results

    db = pg_sessionmaker()
    try:
        from app.models import Invoice

        invoice = db.get(Invoice, invoice_id)
        adjustments = get_invoice_adjustments(db, invoice)
        # The decisive assertion: never over-credited, whatever the
        # interleaving happened to be.
        assert adjustments.credited_total == Decimal("1000.00")
        assert adjustments.remaining_creditable == Decimal("0.00")
        assert adjustments.adjusted_total == Decimal("0.00")
        # And the source invoice is still untouched.
        assert invoice.total == Decimal("1000.00")
    finally:
        db.close()
