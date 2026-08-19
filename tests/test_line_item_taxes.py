"""Phase 28 -- per-line tax rates.

The two properties that matter most, and that everything else here is in
service of:

  1. A mixed-rate document computes each rate's tax on its own base.
  2. A single-rate document produces byte-identical numbers to the
     pre-Phase-28 formula, so no historical invoice can shift by a cent.

Property 2 is why tax is quantized per tax-rate GROUP rather than per
line -- see app.services.invoices.compute_invoice_totals.
"""

from decimal import Decimal

import pytest

from app.schemas import InvoiceLineItemCreate, QuoteLineItemCreate
from app.services.invoices import compute_invoice_totals
from app.services.quotes import convert_quote_to_invoice
from app.tax_groups import group_lines_by_tax_rate
from tests.factories import (
    make_customer,
    make_invoice,
    make_org_with_owner,
    make_product,
    make_quote,
)


def line(qty: str, price: str, rate: str | None = None) -> InvoiceLineItemCreate:
    return InvoiceLineItemCreate(
        description="Item",
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        tax_rate=None if rate is None else Decimal(rate),
    )


# --- A/B/C: single-rate documents -------------------------------------


@pytest.mark.parametrize(
    "rate,expected_tax,expected_total",
    [
        ("0.22", "220.00", "1220.00"),
        ("0.10", "100.00", "1100.00"),
        ("0", "0.00", "1000.00"),
    ],
)
def test_single_line_single_rate(rate, expected_tax, expected_total):
    totals = compute_invoice_totals([line("1", "1000.00", rate)], Decimal("0"))
    assert totals.subtotal == Decimal("1000.00")
    assert totals.tax_amount == Decimal(expected_tax)
    assert totals.total == Decimal(expected_total)
    assert len(totals.tax_groups) == 1
    assert totals.tax_groups[0].rate == Decimal(rate).quantize(Decimal("0.0001"))
    assert totals.tax_groups[0].base == Decimal("1000.00")


# --- D: the headline mixed case ---------------------------------------


def test_mixed_rates_tax_each_base_separately():
    totals = compute_invoice_totals(
        [
            line("1", "1000.00", "0.22"),
            line("1", "500.00", "0.10"),
            line("1", "200.00", "0"),
        ],
        Decimal("0"),
    )
    assert totals.subtotal == Decimal("1700.00")
    # 220 + 50 + 0 -- each computed on its own base, never on the whole
    # subtotal.
    assert totals.tax_amount == Decimal("270.00")
    assert totals.total == Decimal("1970.00")

    # Sorted by rate descending, so the headline rate reads first.
    assert [(g.rate, g.base, g.tax) for g in totals.tax_groups] == [
        (Decimal("0.2200"), Decimal("1000.00"), Decimal("220.00")),
        (Decimal("0.1000"), Decimal("500.00"), Decimal("50.00")),
        (Decimal("0.0000"), Decimal("200.00"), Decimal("0.00")),
    ]


# --- E: several lines sharing one rate collapse into one group --------


def test_lines_sharing_a_rate_form_one_group():
    totals = compute_invoice_totals(
        [line("1", "100.00", "0.22"), line("1", "200.00", "0.22"), line("1", "50.00", "0.10")],
        Decimal("0"),
    )
    assert len(totals.tax_groups) == 2
    assert totals.tax_groups[0].base == Decimal("300.00")
    assert totals.tax_groups[0].tax == Decimal("66.00")
    assert totals.tax_groups[1].tax == Decimal("5.00")
    assert totals.tax_amount == Decimal("71.00")


def test_equivalent_rate_scales_do_not_split_into_two_groups():
    """Decimal("0.22") and Decimal("0.2200") are the same rate and must
    not render as two identical-looking 22% rows."""
    totals = compute_invoice_totals(
        [line("1", "100.00", "0.22"), line("1", "100.00", "0.2200")], Decimal("0")
    )
    assert len(totals.tax_groups) == 1
    assert totals.tax_groups[0].base == Decimal("200.00")


# --- F/G: decimals and rounding ---------------------------------------


def test_decimal_quantities_and_prices():
    """Pins the rounding MODE as well as the arithmetic.

    2.5 * 33.33 = 83.325 exactly, and the project quantizes with
    Decimal's context default, ROUND_HALF_EVEN (banker's rounding) -- so
    this lands on 83.32, not the 83.33 that half-up would give. Phase 28
    deliberately did not change this; the mode is inherited untouched
    from _quantize_money, and this test exists so a future change to it
    is a visible decision rather than a silent drift in every total.
    """
    totals = compute_invoice_totals([line("2.5", "33.33", "0.22")], Decimal("0"))
    assert totals.subtotal == Decimal("83.32")
    assert totals.tax_amount == Decimal("18.33")  # 83.32 * 0.22 = 18.3304
    assert totals.total == Decimal("101.65")


def test_group_rounding_matches_legacy_document_level_rounding():
    """The compatibility guarantee, stated as arithmetic.

    Two 0.05 lines at 10%: rounding per LINE would give 0.01 + 0.01 =
    0.02, but the pre-Phase-28 formula rounds the document once and gets
    0.01. Grouping must reproduce the legacy answer.
    """
    lines = [line("1", "0.05", "0.10"), line("1", "0.05", "0.10")]
    totals = compute_invoice_totals(lines, Decimal("0"))

    legacy_subtotal = Decimal("0.10")
    legacy_tax = (legacy_subtotal * Decimal("0.10")).quantize(Decimal("0.01"))
    assert totals.tax_amount == legacy_tax == Decimal("0.01")


@pytest.mark.parametrize(
    "qty,price,rate",
    [
        ("1", "0.01", "0.22"),
        ("3", "33.33", "0.10"),
        ("7", "14.29", "0.22"),
        ("1", "999999.99", "0.22"),
        ("0.3333", "3.00", "0.22"),
    ],
)
def test_single_rate_always_equals_the_legacy_formula(qty, price, rate):
    """Exhaustive-ish guard on property 2: for ANY single-rate document,
    the new grouped computation must equal quantize(subtotal * rate)."""
    totals = compute_invoice_totals([line(qty, price, rate)], Decimal("0"))
    legacy = (totals.subtotal * Decimal(rate)).quantize(Decimal("0.01"))
    assert totals.tax_amount == legacy


# --- M: API backwards compatibility -----------------------------------


def test_line_without_rate_inherits_the_document_rate():
    """The compatibility contract: a client that never heard of per-line
    tax posts only a document rate and gets the old numbers."""
    totals = compute_invoice_totals([line("1", "1000.00"), line("1", "500.00")], Decimal("0.22"))
    assert totals.subtotal == Decimal("1500.00")
    assert totals.tax_amount == Decimal("330.00")
    assert len(totals.tax_groups) == 1


def test_explicit_zero_overrides_the_document_rate():
    """0.0 is NOT the same as omitted: it means "genuinely exempt"."""
    totals = compute_invoice_totals(
        [line("1", "1000.00"), line("1", "500.00", "0")], Decimal("0.22")
    )
    assert totals.tax_amount == Decimal("220.00")
    assert totals.total == Decimal("1720.00")


def test_mixed_supplied_and_omitted_rates():
    totals = compute_invoice_totals(
        [line("1", "1000.00", "0.10"), line("1", "500.00")], Decimal("0.22")
    )
    # 1000 @ 10% = 100 ; 500 inherits 22% = 110
    assert totals.tax_amount == Decimal("210.00")


# --- persistence, products, conversion ---------------------------------


def test_created_invoice_persists_the_resolved_rate_per_line(db_session):
    owner = make_org_with_owner(db_session, email="o@example.com", org_name="Acme")
    invoice = make_invoice(
        db_session,
        owner.organization,
        owner.user,
        line_items=[line("1", "1000.00", "0.22"), line("1", "200.00", "0")],
        tax_rate=Decimal("0"),
    )
    rates = sorted(li.tax_rate for li in invoice.line_items)
    assert rates == [Decimal("0.0000"), Decimal("0.2200")]
    assert invoice.tax_amount == Decimal("220.00")
    assert invoice.total == Decimal("1420.00")


def test_inherited_rate_is_persisted_concretely_not_left_at_zero(db_session):
    """Invoices have no document-level rate column, so a line that
    inherited the request's rate must store that concrete number or the
    invoice would no longer describe its own tax."""
    owner = make_org_with_owner(db_session, email="o2@example.com", org_name="Acme2")
    invoice = make_invoice(
        db_session,
        owner.organization,
        owner.user,
        line_items=[line("1", "1000.00")],
        tax_rate=Decimal("0.22"),
    )
    assert invoice.line_items[0].tax_rate == Decimal("0.2200")


def test_line_override_does_not_modify_the_product(db_session):
    owner = make_org_with_owner(db_session, email="o3@example.com", org_name="Acme3")
    product = make_product(db_session, owner.organization, name="Widget")
    product.default_tax_rate = Decimal("0.22")
    db_session.commit()

    make_invoice(
        db_session,
        owner.organization,
        owner.user,
        line_items=[
            InvoiceLineItemCreate(
                description="Widget",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                tax_rate=Decimal("0.10"),
                product_id=product.id,
            )
        ],
        tax_rate=Decimal("0"),
    )
    db_session.refresh(product)
    assert product.default_tax_rate == Decimal("0.2200")


def test_changing_a_product_later_never_alters_an_issued_invoice(db_session):
    """The historical-snapshot rule, end to end."""
    owner = make_org_with_owner(db_session, email="o4@example.com", org_name="Acme4")
    product = make_product(db_session, owner.organization, name="Service")
    product.default_tax_rate = Decimal("0.22")
    db_session.commit()

    invoice = make_invoice(
        db_session,
        owner.organization,
        owner.user,
        line_items=[
            InvoiceLineItemCreate(
                description="Service",
                quantity=Decimal("1"),
                unit_price=Decimal("1000.00"),
                tax_rate=Decimal("0.22"),
                product_id=product.id,
            )
        ],
        tax_rate=Decimal("0"),
    )
    original_total = invoice.total

    product.default_tax_rate = Decimal("0.10")
    db_session.commit()
    db_session.refresh(invoice)

    assert invoice.line_items[0].tax_rate == Decimal("0.2200")
    assert invoice.tax_amount == Decimal("220.00")
    assert invoice.total == original_total


# --- K: quote -> invoice ----------------------------------------------


def test_quote_to_invoice_preserves_per_line_taxes(db_session):
    owner = make_org_with_owner(db_session, email="o5@example.com", org_name="Acme5")
    customer = make_customer(db_session, owner.organization, email="c@example.com")
    quote = make_quote(
        db_session,
        owner.organization,
        owner.user,
        customer=customer,
        line_items=[
            QuoteLineItemCreate(
                description="A", quantity=Decimal("1"), unit_price=Decimal("1000.00"),
                tax_rate=Decimal("0.22"),
            ),
            QuoteLineItemCreate(
                description="B", quantity=Decimal("1"), unit_price=Decimal("500.00"),
                tax_rate=Decimal("0.10"),
            ),
            QuoteLineItemCreate(
                description="C", quantity=Decimal("1"), unit_price=Decimal("200.00"),
                tax_rate=Decimal("0"),
            ),
        ],
        tax_rate=Decimal("0"),
    )
    assert quote.tax_amount == Decimal("270.00")

    from app.quote_status import QuoteStatus

    quote.status = QuoteStatus.accepted.value
    db_session.commit()

    result = convert_quote_to_invoice(db_session, owner.organization.id, quote, owner.user)
    invoice = result.invoice

    assert invoice.subtotal == quote.subtotal
    assert invoice.tax_amount == quote.tax_amount
    assert invoice.total == quote.total
    assert sorted(li.tax_rate for li in invoice.line_items) == [
        Decimal("0.0000"),
        Decimal("0.1000"),
        Decimal("0.2200"),
    ]


# --- L: migration preserves historical totals -------------------------


@pytest.mark.parametrize(
    "subtotal,rate",
    [
        ("1000.00", "0.22"),
        ("1000.00", "0.10"),
        ("1000.00", "0"),
        ("83.33", "0.22"),
        ("7.77", "0.10"),
        ("123456.78", "0.22"),
    ],
)
def test_backfilled_rate_recomputes_the_stored_total_exactly(subtotal, rate):
    """Simulates what the migration does for a pre-Phase-28 invoice:
    invoices stored only tax_amount, so the rate is recovered as
    tax_amount / subtotal. Recomputing with that recovered rate must
    reproduce the stored figures exactly.
    """
    sub = Decimal(subtotal)
    stored_tax = (sub * Decimal(rate)).quantize(Decimal("0.01"))

    recovered = (
        (stored_tax / sub).quantize(Decimal("0.0001")) if sub > 0 else Decimal("0")
    )

    groups = group_lines_by_tax_rate(
        [type("L", (), {"line_total": sub, "tax_rate": recovered})()]
    )
    assert sum(g.tax for g in groups) == stored_tax


def test_zero_subtotal_invoice_backfills_to_zero_rate():
    groups = group_lines_by_tax_rate(
        [type("L", (), {"line_total": Decimal("0.00"), "tax_rate": Decimal("0")})()]
    )
    assert groups[0].tax == Decimal("0.00")
