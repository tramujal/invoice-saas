"""Phase 29 -- credit and debit notes: domain behavior.

The properties these tests exist to defend, in order of importance:

  1. Invoice.total is NEVER mutated.
  2. Over-crediting is impossible, at the document AND the line level.
  3. Only issued notes affect anything.
  4. Tax comes from Phase 28, unchanged, including historical snapshots.
"""

from decimal import Decimal

import pytest

from app.adjustment_note_status import AdjustmentNoteStatus
from app.adjustment_note_type import AdjustmentNoteType
from app.models import AdjustmentNote
from app.schemas import AdjustmentNoteLineItemCreate, InvoiceLineItemCreate
from app.services.adjustment_notes import (
    DebitLineCannotReferenceSourceError,
    EmptyNoteError,
    LineOverCreditError,
    NoteAlreadyVoidError,
    NoteNotDraftError,
    NoteNotIssuedError,
    OverCreditError,
    SourceInvoiceNotFoundError,
    SourceLineNotOnInvoiceError,
    create_adjustment_note,
    get_creditable_lines,
    get_invoice_adjustments,
    issue_adjustment_note,
    signed_total,
    void_adjustment_note,
)
from tests.factories import make_customer, make_invoice, make_org_with_owner


def inv_line(desc, qty, price, rate="0"):
    return InvoiceLineItemCreate(
        description=desc,
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        tax_rate=Decimal(rate),
    )


def note_line(qty, price=None, rate=None, desc="Adjustment", source=None):
    return AdjustmentNoteLineItemCreate(
        description=desc,
        quantity=Decimal(qty),
        unit_price=None if price is None else Decimal(price),
        tax_rate=None if rate is None else Decimal(rate),
        source_invoice_line_item_id=source,
    )


@pytest.fixture
def org(db_session):
    return make_org_with_owner(db_session, email="notes@example.com", org_name="Notes Co")


@pytest.fixture
def mixed_invoice(db_session, org):
    """The scenario from the phase brief: 1000@22 / 500@10 / 200@0
    -> subtotal 1700, tax 270, total 1970."""
    customer = make_customer(db_session, org.organization, email="c@example.com")
    invoice = make_invoice(
        db_session,
        org.organization,
        org.user,
        customer=customer,
        line_items=[
            inv_line("A", "1", "1000.00", "0.22"),
            inv_line("B", "1", "500.00", "0.10"),
            inv_line("C", "1", "200.00", "0"),
        ],
        tax_rate=Decimal("0"),
    )
    assert (invoice.subtotal, invoice.tax_amount, invoice.total) == (
        Decimal("1700.00"),
        Decimal("270.00"),
        Decimal("1970.00"),
    )
    return invoice


def credit(db, org, invoice, lines, **kw):
    return create_adjustment_note(
        db,
        org.organization.id,
        note_type=AdjustmentNoteType.credit,
        source_invoice_id=invoice.id,
        line_items=lines,
        current_user=org.user,
        **kw,
    )


def debit(db, org, invoice, lines, **kw):
    return create_adjustment_note(
        db,
        org.organization.id,
        note_type=AdjustmentNoteType.debit,
        source_invoice_id=invoice.id,
        line_items=lines,
        current_user=org.user,
        **kw,
    )


# --- creation and derivation ------------------------------------------


def test_note_derives_org_customer_and_currency_from_the_invoice(db_session, org, mixed_invoice):
    note = credit(db_session, org, mixed_invoice, [note_line("1", "100.00", "0.22")])
    assert note.organization_id == mixed_invoice.organization_id
    assert note.customer_id == mixed_invoice.customer_id
    assert note.currency_code == mixed_invoice.currency_code
    assert note.source_invoice_id == mixed_invoice.id
    assert note.status == AdjustmentNoteStatus.draft.value


def test_source_invoice_is_required_and_tenant_scoped(db_session, org):
    other = make_org_with_owner(db_session, email="other@example.com", org_name="Other Co")
    foreign = make_invoice(db_session, other.organization, other.user)
    # The foreign invoice is indistinguishable from a missing one.
    with pytest.raises(SourceInvoiceNotFoundError):
        credit(db_session, org, foreign, [note_line("1", "10.00")])


def test_empty_note_is_rejected(db_session, org, mixed_invoice):
    with pytest.raises(EmptyNoteError):
        credit(db_session, org, mixed_invoice, [])


def test_a_line_cannot_reference_another_invoices_line(db_session, org, mixed_invoice):
    second = make_invoice(db_session, org.organization, org.user)
    foreign_line_id = second.line_items[0].id
    with pytest.raises(SourceLineNotOnInvoiceError):
        credit(db_session, org, mixed_invoice, [note_line("1", "10.00", source=foreign_line_id)])


# --- taxes: Phase 28, unchanged ---------------------------------------


@pytest.mark.parametrize(
    "rate,expected_tax,expected_total",
    [("0.22", "220.00", "1220.00"), ("0.10", "100.00", "1100.00"), ("0", "0.00", "1000.00")],
)
def test_single_rate_note(db_session, org, mixed_invoice, rate, expected_tax, expected_total):
    note = credit(db_session, org, mixed_invoice, [note_line("1", "1000.00", rate)])
    assert note.subtotal == Decimal("1000.00")
    assert note.tax_amount == Decimal(expected_tax)
    assert note.total == Decimal(expected_total)


def test_mixed_rate_note_matches_the_brief(db_session, org, mixed_invoice):
    note = credit(
        db_session,
        org,
        mixed_invoice,
        [note_line("1", "1000.00", "0.22"), note_line("1", "500.00", "0.10"), note_line("1", "200.00", "0")],
    )
    assert (note.subtotal, note.tax_amount, note.total) == (
        Decimal("1700.00"),
        Decimal("270.00"),
        Decimal("1970.00"),
    )
    assert [(g.rate, g.base, g.tax) for g in note.tax_groups] == [
        (Decimal("0.2200"), Decimal("1000.00"), Decimal("220.00")),
        (Decimal("0.1000"), Decimal("500.00"), Decimal("50.00")),
        (Decimal("0.0000"), Decimal("200.00"), Decimal("0.00")),
    ]


def test_mixed_rate_debit_note(db_session, org, mixed_invoice):
    note = debit(
        db_session,
        org,
        mixed_invoice,
        [note_line("1", "100.00", "0.22", desc="Extra"), note_line("1", "50.00", "0.10", desc="Extra 2")],
    )
    assert note.total == Decimal("177.00")  # 150 + 22 + 5


def test_line_inherits_the_invoice_lines_tax_snapshot(db_session, org, mixed_invoice):
    """The whole point of the source reference: crediting part of a line
    must use THAT line's historical rate, not a rate supplied now and not
    the product's current default."""
    source = mixed_invoice.line_items[0]  # 1000 @ 22%
    note = credit(db_session, org, mixed_invoice, [note_line("1", None, None, source=source.id)])
    assert note.line_items[0].tax_rate == Decimal("0.2200")
    assert note.line_items[0].unit_price == Decimal("1000.00")
    assert note.total == Decimal("1220.00")


def test_changing_the_product_later_does_not_move_an_issued_note(db_session, org):
    from tests.factories import make_product

    product = make_product(db_session, org.organization, name="Widget")
    product.default_tax_rate = Decimal("0.22")
    db_session.commit()

    invoice = make_invoice(
        db_session,
        org.organization,
        org.user,
        line_items=[
            InvoiceLineItemCreate(
                description="Widget",
                quantity=Decimal("1"),
                unit_price=Decimal("1000.00"),
                tax_rate=Decimal("0.22"),
                product_id=product.id,
            )
        ],
        tax_rate=Decimal("0"),
    )
    note = credit(
        db_session, org, invoice, [note_line("1", None, None, source=invoice.line_items[0].id)]
    )
    issue_adjustment_note(db_session, note, current_user=org.user)
    before = note.total

    product.default_tax_rate = Decimal("0.05")
    db_session.commit()
    db_session.refresh(note)

    assert note.line_items[0].tax_rate == Decimal("0.2200")
    assert note.total == before


# --- lifecycle --------------------------------------------------------


def test_draft_notes_are_economically_inert(db_session, org, mixed_invoice):
    credit(db_session, org, mixed_invoice, [note_line("1", "500.00")])
    adj = get_invoice_adjustments(db_session, mixed_invoice)
    assert adj.credited_total == Decimal("0.00")
    assert adj.adjusted_total == mixed_invoice.total
    assert adj.remaining_creditable == mixed_invoice.total


def test_issuing_makes_a_note_count(db_session, org, mixed_invoice):
    note = credit(db_session, org, mixed_invoice, [note_line("1", "500.00")])
    issue_adjustment_note(db_session, note, current_user=org.user)

    adj = get_invoice_adjustments(db_session, mixed_invoice)
    assert adj.credited_total == Decimal("500.00")
    assert adj.adjusted_total == Decimal("1470.00")
    assert adj.remaining_creditable == Decimal("1470.00")
    assert note.issued_at is not None
    assert note.issue_date is not None


def test_issue_is_only_valid_from_draft(db_session, org, mixed_invoice):
    note = credit(db_session, org, mixed_invoice, [note_line("1", "100.00")])
    issue_adjustment_note(db_session, note, current_user=org.user)
    with pytest.raises(NoteNotDraftError):
        issue_adjustment_note(db_session, note, current_user=org.user)


def test_void_requires_issued_and_is_terminal(db_session, org, mixed_invoice):
    draft = credit(db_session, org, mixed_invoice, [note_line("1", "100.00")])
    with pytest.raises(NoteNotIssuedError):
        void_adjustment_note(db_session, draft, current_user=org.user)

    issue_adjustment_note(db_session, draft, current_user=org.user)
    void_adjustment_note(db_session, draft, current_user=org.user)
    with pytest.raises(NoteAlreadyVoidError):
        void_adjustment_note(db_session, draft, current_user=org.user)


def test_voiding_removes_the_economic_effect_and_frees_the_ceiling(db_session, org, mixed_invoice):
    note = credit(db_session, org, mixed_invoice, [note_line("1", "1000.00")])
    issue_adjustment_note(db_session, note, current_user=org.user)
    assert get_invoice_adjustments(db_session, mixed_invoice).credited_total == Decimal("1000.00")

    void_adjustment_note(db_session, note, current_user=org.user)
    adj = get_invoice_adjustments(db_session, mixed_invoice)
    assert adj.credited_total == Decimal("0.00")
    assert adj.adjusted_total == mixed_invoice.total
    assert adj.remaining_creditable == mixed_invoice.total
    # Retained, never deleted.
    assert db_session.get(AdjustmentNote, note.id) is not None


def test_the_source_invoice_total_is_never_mutated(db_session, org, mixed_invoice):
    original = mixed_invoice.total
    for amount in ("500.00", "300.00"):
        note = credit(db_session, org, mixed_invoice, [note_line("1", amount)])
        issue_adjustment_note(db_session, note, current_user=org.user)
    debit_note = debit(db_session, org, mixed_invoice, [note_line("1", "100.00", desc="Extra")])
    issue_adjustment_note(db_session, debit_note, current_user=org.user)

    db_session.refresh(mixed_invoice)
    assert mixed_invoice.total == original
    assert mixed_invoice.subtotal == Decimal("1700.00")


# --- the adjusted view ------------------------------------------------


def test_adjusted_total_combines_credits_and_debits(db_session, org, mixed_invoice):
    c = credit(db_session, org, mixed_invoice, [note_line("1", "500.00")])
    issue_adjustment_note(db_session, c, current_user=org.user)
    d = debit(db_session, org, mixed_invoice, [note_line("1", "200.00", desc="Extra")])
    issue_adjustment_note(db_session, d, current_user=org.user)

    adj = get_invoice_adjustments(db_session, mixed_invoice)
    assert adj.original_total == Decimal("1970.00")
    assert adj.credited_total == Decimal("500.00")
    assert adj.debited_total == Decimal("200.00")
    assert adj.adjusted_total == Decimal("1670.00")


def test_debit_notes_do_not_raise_the_credit_ceiling(db_session, org, mixed_invoice):
    """The documented decision: the ceiling tracks the ORIGINAL sale, so a
    debit note cannot be used to unlock extra reversibility."""
    d = debit(db_session, org, mixed_invoice, [note_line("1", "500.00", desc="Extra")])
    issue_adjustment_note(db_session, d, current_user=org.user)

    adj = get_invoice_adjustments(db_session, mixed_invoice)
    assert adj.debited_total == Decimal("500.00")
    assert adj.remaining_creditable == Decimal("1970.00")  # unchanged by the debit

    with pytest.raises(OverCreditError):
        credit(db_session, org, mixed_invoice, [note_line("1", "1970.01")])


def test_signed_total_is_the_only_place_direction_is_applied():
    assert signed_total(AdjustmentNoteType.credit, Decimal("100")) == Decimal("-100")
    assert signed_total(AdjustmentNoteType.debit, Decimal("100")) == Decimal("100")


# --- over-credit protection -------------------------------------------


def test_credit_beyond_the_remaining_amount_is_blocked(db_session, org, mixed_invoice):
    first = credit(db_session, org, mixed_invoice, [note_line("1", "1000.00")])  # total 1000
    issue_adjustment_note(db_session, first, current_user=org.user)

    remaining = get_invoice_adjustments(db_session, mixed_invoice).remaining_creditable
    assert remaining == Decimal("970.00")

    with pytest.raises(OverCreditError) as exc:
        credit(db_session, org, mixed_invoice, [note_line("1", "970.01")])
    assert exc.value.remaining == Decimal("970.00")


def test_crediting_exactly_the_remaining_amount_succeeds(db_session, org, mixed_invoice):
    first = credit(db_session, org, mixed_invoice, [note_line("1", "1000.00")])
    issue_adjustment_note(db_session, first, current_user=org.user)

    exact = credit(db_session, org, mixed_invoice, [note_line("1", "970.00")])
    issue_adjustment_note(db_session, exact, current_user=org.user)

    adj = get_invoice_adjustments(db_session, mixed_invoice)
    assert adj.credited_total == Decimal("1970.00")
    assert adj.adjusted_total == Decimal("0.00")
    assert adj.remaining_creditable == Decimal("0.00")


def test_the_brief_example_1000_credited_300_leaves_700(db_session, org):
    invoice = make_invoice(
        db_session,
        org.organization,
        org.user,
        line_items=[inv_line("Item", "1", "1000.00", "0")],
        tax_rate=Decimal("0"),
    )
    assert invoice.total == Decimal("1000.00")

    first = credit(db_session, org, invoice, [note_line("1", "300.00")])
    issue_adjustment_note(db_session, first, current_user=org.user)
    assert get_invoice_adjustments(db_session, invoice).remaining_creditable == Decimal("700.00")

    with pytest.raises(OverCreditError):
        credit(db_session, org, invoice, [note_line("1", "701.00")])

    ok = credit(db_session, org, invoice, [note_line("1", "700.00")])
    issue_adjustment_note(db_session, ok, current_user=org.user)
    assert get_invoice_adjustments(db_session, invoice).remaining_creditable == Decimal("0.00")


def test_the_ceiling_is_rechecked_at_issue_time(db_session, org, mixed_invoice):
    """Two drafts can each be within the ceiling at creation; the second
    must fail when it is ISSUED after the first already consumed it."""
    a = credit(db_session, org, mixed_invoice, [note_line("1", "1500.00")])
    b = credit(db_session, org, mixed_invoice, [note_line("1", "1500.00")])

    issue_adjustment_note(db_session, a, current_user=org.user)
    with pytest.raises(OverCreditError):
        issue_adjustment_note(db_session, b, current_user=org.user)


# --- line-level limits ------------------------------------------------


def test_line_level_over_credit_is_blocked_even_within_the_document_ceiling(
    db_session, org, mixed_invoice
):
    """Crediting line A (1000) twice totals 2000 > its own value, while
    2000 could otherwise look acceptable against a 1970 document only by
    coincidence -- so this is checked per line, not only in aggregate."""
    line_a = mixed_invoice.line_items[0]
    first = credit(db_session, org, mixed_invoice, [note_line("1", "1000.00", "0.22", source=line_a.id)])
    issue_adjustment_note(db_session, first, current_user=org.user)

    with pytest.raises(LineOverCreditError) as exc:
        credit(db_session, org, mixed_invoice, [note_line("1", "1.00", "0.22", source=line_a.id)])
    assert exc.value.remaining == Decimal("0.00")


def test_partial_line_credits_accumulate(db_session, org, mixed_invoice):
    line_a = mixed_invoice.line_items[0]  # 1000
    for amount in ("400.00", "300.00"):
        n = credit(db_session, org, mixed_invoice, [note_line("1", amount, "0.22", source=line_a.id)])
        issue_adjustment_note(db_session, n, current_user=org.user)

    lines = {row["invoice_line_item_id"]: row for row in get_creditable_lines(db_session, mixed_invoice)}
    assert lines[line_a.id]["credited_total"] == Decimal("700.00")
    assert lines[line_a.id]["remaining_creditable"] == Decimal("300.00")

    with pytest.raises(LineOverCreditError):
        credit(db_session, org, mixed_invoice, [note_line("1", "300.01", "0.22", source=line_a.id)])


def test_two_lines_in_one_note_against_the_same_source_are_summed(db_session, org, mixed_invoice):
    """Splitting an over-credit across two lines of the SAME note must not
    slip past the per-line check."""
    line_a = mixed_invoice.line_items[0]  # 1000
    with pytest.raises(LineOverCreditError):
        credit(
            db_session,
            org,
            mixed_invoice,
            [
                note_line("1", "600.00", "0.22", source=line_a.id),
                note_line("1", "600.00", "0.22", source=line_a.id),
            ],
        )


def test_voided_notes_release_line_level_credit(db_session, org, mixed_invoice):
    line_a = mixed_invoice.line_items[0]
    n = credit(db_session, org, mixed_invoice, [note_line("1", "1000.00", "0.22", source=line_a.id)])
    issue_adjustment_note(db_session, n, current_user=org.user)
    void_adjustment_note(db_session, n, current_user=org.user)

    lines = {row["invoice_line_item_id"]: row for row in get_creditable_lines(db_session, mixed_invoice)}
    assert lines[line_a.id]["remaining_creditable"] == Decimal("1000.00")


def test_debit_lines_cannot_reference_an_invoice_line(db_session, org, mixed_invoice):
    with pytest.raises(DebitLineCannotReferenceSourceError):
        debit(
            db_session,
            org,
            mixed_invoice,
            [note_line("1", "10.00", "0", source=mixed_invoice.line_items[0].id)],
        )


# --- numbering --------------------------------------------------------


def test_credit_and_debit_numbering_are_separate_sequences(db_session, org, mixed_invoice):
    c1 = credit(db_session, org, mixed_invoice, [note_line("1", "10.00")])
    d1 = debit(db_session, org, mixed_invoice, [note_line("1", "10.00", desc="Extra")])
    c2 = credit(db_session, org, mixed_invoice, [note_line("1", "10.00")])

    assert c1.formatted_number == "CN-000001"
    assert c2.formatted_number == "CN-000002"
    assert d1.formatted_number == "DN-000001"


def test_note_numbering_never_consumes_invoice_numbers(db_session, org, mixed_invoice):
    before = org.organization.next_invoice_number
    credit(db_session, org, mixed_invoice, [note_line("1", "10.00")])
    debit(db_session, org, mixed_invoice, [note_line("1", "10.00", desc="Extra")])
    db_session.refresh(org.organization)
    assert org.organization.next_invoice_number == before


def test_numbering_is_scoped_per_organization(db_session, org, mixed_invoice):
    other = make_org_with_owner(db_session, email="second@example.com", org_name="Second Co")
    other_invoice = make_invoice(db_session, other.organization, other.user)

    mine = credit(db_session, org, mixed_invoice, [note_line("1", "10.00")])
    theirs = create_adjustment_note(
        db_session,
        other.organization.id,
        note_type=AdjustmentNoteType.credit,
        source_invoice_id=other_invoice.id,
        line_items=[note_line("1", "10.00")],
        current_user=other.user,
    )
    # Both are number 1 in their own tenant -- sequences never collide.
    assert mine.formatted_number == theirs.formatted_number == "CN-000001"
    assert mine.organization_id != theirs.organization_id


def test_create_and_issue_in_one_call(db_session, org, mixed_invoice):
    note = credit(db_session, org, mixed_invoice, [note_line("1", "100.00")], issue_immediately=True)
    assert note.status == AdjustmentNoteStatus.issued.value
    assert get_invoice_adjustments(db_session, mixed_invoice).credited_total == Decimal("100.00")
