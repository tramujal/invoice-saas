"""Currency inference/validation on invoice creation -- see
app.currency.resolve_document_currency_code, the single function shared by
the direct HTTP path and the AI Agent tool for both invoices and quotes."""

from tests.factories import make_customer, make_org_with_owner, make_product


def _create_invoice(client, org_id, headers, **overrides):
    body = {
        "line_items": [{"description": "Manual line", "quantity": "1", "unit_price": "10.00"}],
    }
    body.update(overrides)
    return client.post(f"/organizations/{org_id}/invoices", json=body, headers=headers)


def test_first_product_line_determines_currency_when_omitted(client, db_session):
    owner = make_org_with_owner(db_session, email="owner1@example.com")
    product = make_product(db_session, owner.organization, name="Hosting", currency_code="EUR")

    response = _create_invoice(
        client,
        owner.organization.id,
        owner.auth_headers,
        line_items=[
            {
                "description": "Hosting",
                "quantity": "1",
                "unit_price": "15.00",
                "product_id": product.id,
            }
        ],
    )
    assert response.status_code == 201, response.text
    assert response.json()["currency_code"] == "EUR"


def test_currency_required_when_all_lines_manual_and_omitted(client, db_session):
    owner = make_org_with_owner(db_session, email="owner2@example.com")

    response = _create_invoice(client, owner.organization.id, owner.auth_headers)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "currency_required"


def test_manual_lines_succeed_when_currency_given(client, db_session):
    owner = make_org_with_owner(db_session, email="owner3@example.com")

    response = _create_invoice(
        client, owner.organization.id, owner.auth_headers, currency_code="UYU"
    )
    assert response.status_code == 201, response.text
    assert response.json()["currency_code"] == "UYU"


def test_product_currency_mismatch_against_requested_currency(client, db_session):
    owner = make_org_with_owner(db_session, email="owner4@example.com")
    product = make_product(db_session, owner.organization, name="Hosting", currency_code="EUR")

    response = _create_invoice(
        client,
        owner.organization.id,
        owner.auth_headers,
        currency_code="USD",
        line_items=[
            {
                "description": "Hosting",
                "quantity": "1",
                "unit_price": "15.00",
                "product_id": product.id,
            }
        ],
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "product_currency_mismatch"


def test_product_currency_mismatch_against_inferred_currency(client, db_session):
    owner = make_org_with_owner(db_session, email="owner5@example.com")
    usd_product = make_product(db_session, owner.organization, name="Consulting", currency_code="USD")
    eur_product = make_product(db_session, owner.organization, name="Hosting", currency_code="EUR")

    response = _create_invoice(
        client,
        owner.organization.id,
        owner.auth_headers,
        line_items=[
            {
                "description": "Consulting",
                "quantity": "1",
                "unit_price": "100.00",
                "product_id": usd_product.id,
            },
            {
                "description": "Hosting",
                "quantity": "1",
                "unit_price": "15.00",
                "product_id": eur_product.id,
            },
        ],
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "product_currency_mismatch"


def test_removing_first_line_re_derives_currency_from_new_first_line(client, db_session):
    """Direct contract test for a raw API caller: creating with only a
    compatible second product succeeds and is priced in that product's own
    currency once the (would-be) first, incompatible line is absent."""
    owner = make_org_with_owner(db_session, email="owner6@example.com")
    product = make_product(db_session, owner.organization, name="Support", currency_code="UYU")

    response = _create_invoice(
        client,
        owner.organization.id,
        owner.auth_headers,
        line_items=[
            {
                "description": "Support",
                "quantity": "1",
                "unit_price": "2500.00",
                "product_id": product.id,
            }
        ],
    )
    assert response.status_code == 201, response.text
    assert response.json()["currency_code"] == "UYU"
