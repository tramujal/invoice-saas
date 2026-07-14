"""Currency inference/validation on quote creation and update -- mirrors
tests/invoices/test_invoice_currency.py exactly, plus an update-time test
covering the previously-unvalidated gap in update_quote_record (replacing
line_items never checked product currency against the quote's pinned
currency)."""

from tests.factories import make_org_with_owner, make_product, make_quote


def _create_quote(client, org_id, headers, **overrides):
    body = {
        "line_items": [{"description": "Manual line", "quantity": "1", "unit_price": "10.00"}],
    }
    body.update(overrides)
    return client.post(f"/organizations/{org_id}/quotes", json=body, headers=headers)


def test_first_product_line_determines_currency_when_omitted(client, db_session):
    owner = make_org_with_owner(db_session, email="owner1@example.com")
    product = make_product(db_session, owner.organization, name="Hosting", currency_code="EUR")

    response = _create_quote(
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

    response = _create_quote(client, owner.organization.id, owner.auth_headers)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "currency_required"


def test_manual_lines_succeed_when_currency_given(client, db_session):
    owner = make_org_with_owner(db_session, email="owner3@example.com")

    response = _create_quote(
        client, owner.organization.id, owner.auth_headers, currency_code="UYU"
    )
    assert response.status_code == 201, response.text
    assert response.json()["currency_code"] == "UYU"


def test_product_currency_mismatch_against_requested_currency(client, db_session):
    owner = make_org_with_owner(db_session, email="owner4@example.com")
    product = make_product(db_session, owner.organization, name="Hosting", currency_code="EUR")

    response = _create_quote(
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

    response = _create_quote(
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


def test_update_quote_rejects_incompatible_product_line(client, db_session):
    """The closed gap: update_quote_record's line_items replacement path
    never used to check product currency against the quote's own pinned
    currency at all."""
    owner = make_org_with_owner(db_session, email="owner6@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)  # pinned USD
    eur_product = make_product(db_session, owner.organization, name="Hosting", currency_code="EUR")

    response = client.patch(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}",
        json={
            "line_items": [
                {
                    "description": "Hosting",
                    "quantity": "1",
                    "unit_price": "15.00",
                    "product_id": eur_product.id,
                }
            ]
        },
        headers=owner.auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "product_currency_mismatch"


def test_update_quote_accepts_compatible_product_line(client, db_session):
    owner = make_org_with_owner(db_session, email="owner7@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)  # pinned USD
    usd_product = make_product(db_session, owner.organization, name="Consulting", currency_code="USD")

    response = client.patch(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}",
        json={
            "line_items": [
                {
                    "description": "Consulting",
                    "quantity": "1",
                    "unit_price": "100.00",
                    "product_id": usd_product.id,
                }
            ]
        },
        headers=owner.auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["currency_code"] == "USD"
