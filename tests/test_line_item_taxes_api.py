"""Phase 28 -- HTTP-level behavior of per-line tax: the public API
compatibility contract, the grouped summary, and PDF rendering.

The API surface tested here is shared verbatim with /api/v1 (see
app.routers.api_v1.invoices, which imports the same request/response
schemas), so these assertions cover both.
"""

from app.invoice_pdf import render_invoice_pdf
from app.models import Invoice
from tests.factories import make_customer, make_org_with_owner


def _create(client, owner, lines, tax_rate=None):
    body = {"line_items": lines, "currency_code": "USD"}
    if tax_rate is not None:
        body["tax_rate"] = tax_rate
    return client.post(
        f"/organizations/{owner.organization.id}/invoices",
        json=body,
        headers=owner.auth_headers,
    )


# --- M: backwards compatibility ---------------------------------------


def test_legacy_request_shape_still_works(client, db_session):
    """No per-line tax anywhere, just a document rate -- exactly what an
    existing API client sends. Numbers must be unchanged."""
    owner = make_org_with_owner(db_session, email="api1@example.com")
    response = _create(
        client,
        owner,
        [
            {"description": "A", "quantity": "1", "unit_price": "1000.00"},
            {"description": "B", "quantity": "1", "unit_price": "500.00"},
        ],
        tax_rate="0.22",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["subtotal"] == "1500.00"
    assert body["tax_amount"] == "330.00"
    assert body["total"] == "1830.00"


def test_legacy_response_fields_are_all_still_present(client, db_session):
    owner = make_org_with_owner(db_session, email="api2@example.com")
    body = _create(
        client, owner, [{"description": "A", "quantity": "1", "unit_price": "100.00"}], "0.22"
    ).json()
    for field in ("id", "invoice_number", "subtotal", "tax_amount", "total", "line_items"):
        assert field in body
    # Additive only.
    assert "tax_rate" in body["line_items"][0]
    assert "tax_groups" in body


def test_per_line_tax_accepted_and_echoed(client, db_session):
    owner = make_org_with_owner(db_session, email="api3@example.com")
    response = _create(
        client,
        owner,
        [
            {"description": "A", "quantity": "1", "unit_price": "1000.00", "tax_rate": "0.22"},
            {"description": "B", "quantity": "1", "unit_price": "500.00", "tax_rate": "0.10"},
            {"description": "C", "quantity": "1", "unit_price": "200.00", "tax_rate": "0"},
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["subtotal"] == "1700.00"
    assert body["tax_amount"] == "270.00"
    assert body["total"] == "1970.00"
    assert [li["tax_rate"] for li in body["line_items"]] == ["0.2200", "0.1000", "0.0000"]


def test_tax_groups_report_base_and_tax_per_rate(client, db_session):
    owner = make_org_with_owner(db_session, email="api4@example.com")
    body = _create(
        client,
        owner,
        [
            {"description": "A", "quantity": "1", "unit_price": "1000.00", "tax_rate": "0.22"},
            {"description": "B", "quantity": "1", "unit_price": "500.00", "tax_rate": "0.10"},
            {"description": "C", "quantity": "1", "unit_price": "200.00", "tax_rate": "0"},
        ],
    ).json()

    assert [(g["rate"], g["base"], g["tax"]) for g in body["tax_groups"]] == [
        ("0.2200", "1000.00", "220.00"),
        ("0.1000", "500.00", "50.00"),
        ("0.0000", "200.00", "0.00"),
    ]


def test_single_rate_invoice_still_reports_one_group(client, db_session):
    owner = make_org_with_owner(db_session, email="api5@example.com")
    body = _create(
        client, owner, [{"description": "A", "quantity": "2", "unit_price": "50.00"}], "0.22"
    ).json()
    assert len(body["tax_groups"]) == 1
    assert body["tax_groups"][0]["tax"] == body["tax_amount"]


def test_rate_out_of_range_is_rejected(client, db_session):
    """Validation is not loosened to accommodate the new field."""
    owner = make_org_with_owner(db_session, email="api6@example.com")
    response = _create(
        client, owner, [{"description": "A", "quantity": "1", "unit_price": "10.00", "tax_rate": "1.5"}]
    )
    assert response.status_code == 422


# --- N: PDF -----------------------------------------------------------


def test_pdf_renders_for_a_mixed_rate_invoice(client, db_session):
    owner = make_org_with_owner(db_session, email="pdf1@example.com")
    make_customer(db_session, owner.organization, email="c@example.com")
    body = _create(
        client,
        owner,
        [
            {"description": "A", "quantity": "1", "unit_price": "1000.00", "tax_rate": "0.22"},
            {"description": "B", "quantity": "1", "unit_price": "500.00", "tax_rate": "0.10"},
            {"description": "C", "quantity": "1", "unit_price": "200.00", "tax_rate": "0"},
        ],
    ).json()

    invoice = db_session.get(Invoice, body["id"])
    pdf = render_invoice_pdf(invoice)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_pdf_still_renders_for_a_single_rate_invoice(client, db_session):
    owner = make_org_with_owner(db_session, email="pdf2@example.com")
    body = _create(
        client, owner, [{"description": "A", "quantity": "1", "unit_price": "100.00"}], "0.22"
    ).json()
    invoice = db_session.get(Invoice, body["id"])
    assert render_invoice_pdf(invoice).startswith(b"%PDF")


def test_pdf_line_tax_column_appears_only_when_rates_differ(client, db_session):
    """The column is a mixed-rate affordance; a single-rate invoice keeps
    its original layout."""
    from app.pdf_tax_rows import should_show_line_tax_column

    owner = make_org_with_owner(db_session, email="pdf3@example.com")
    single = db_session.get(
        Invoice,
        _create(
            client, owner, [{"description": "A", "quantity": "1", "unit_price": "100.00"}], "0.22"
        ).json()["id"],
    )
    mixed = db_session.get(
        Invoice,
        _create(
            client,
            owner,
            [
                {"description": "A", "quantity": "1", "unit_price": "100.00", "tax_rate": "0.22"},
                {"description": "B", "quantity": "1", "unit_price": "100.00", "tax_rate": "0.10"},
            ],
        ).json()["id"],
    )
    assert should_show_line_tax_column(single.tax_groups) is False
    assert should_show_line_tax_column(mixed.tax_groups) is True


def test_exempt_group_is_labelled_exempt_not_zero_tax():
    """A 0% bucket must never read as "Tax 0%" -- see
    app.pdf_tax_rows.tax_group_label."""
    from decimal import Decimal

    from app.pdf_tax_rows import tax_group_label
    from app.tax_groups import TaxGroup

    exempt = TaxGroup(rate=Decimal("0"), base=Decimal("200.00"), tax=Decimal("0.00"))
    assert tax_group_label(exempt, "en") == "Exempt"
    assert tax_group_label(exempt, "es") == "Exento"

    taxed = TaxGroup(rate=Decimal("0.22"), base=Decimal("1000.00"), tax=Decimal("220.00"))
    assert "22%" in tax_group_label(taxed, "en")
