from decimal import Decimal

from app.quote_status import QuoteStatus
from tests.factories import make_customer, make_org_with_owner, make_product, make_quote


def _mark_sent(db_session, quote):
    quote.status = QuoteStatus.sent.value
    db_session.commit()
    db_session.refresh(quote)
    return quote


def test_create_quote_via_api(client, db_session):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    customer = make_customer(db_session, owner.organization)

    response = client.post(
        f"/organizations/{owner.organization.id}/quotes",
        json={
            "line_items": [
                {"description": "Consulting", "quantity": "2", "unit_price": "50.00"}
            ],
            "customer_id": customer.id,
        },
        headers=owner.auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["total"] == "100.00"


def test_duplicate_quote_creates_independent_draft(client, db_session):
    owner = make_org_with_owner(db_session, email="owner2@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)

    response = client.post(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}/duplicate",
        headers=owner.auth_headers,
    )
    assert response.status_code == 201
    duplicated = response.json()
    assert duplicated["id"] != quote.id
    assert duplicated["quote_number"] != quote.quote_number


def test_send_quote_email_flips_status_and_uses_fake_sender(client, db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner3@example.com")
    customer = make_customer(db_session, owner.organization, email="customer@example.com")
    quote = make_quote(db_session, owner.organization, owner.user, customer=customer)

    response = client.post(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}/send-email",
        headers=owner.auth_headers,
    )
    assert response.status_code == 200
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "customer@example.com"

    db_session.refresh(quote)
    assert quote.status == QuoteStatus.sent.value


def test_public_accept_and_already_decided(client, db_session):
    owner = make_org_with_owner(db_session, email="owner4@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)
    _mark_sent(db_session, quote)

    first = client.post(f"/quotes/public/{quote.public_token}/accept")
    assert first.status_code == 200
    assert first.json()["status"] == "accepted"

    second = client.post(f"/quotes/public/{quote.public_token}/accept")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "quote_already_responded"


def test_public_reject(client, db_session):
    owner = make_org_with_owner(db_session, email="owner5@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)
    _mark_sent(db_session, quote)

    response = client.post(f"/quotes/public/{quote.public_token}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_public_quote_unknown_token_is_404(client):
    response = client.get("/quotes/public/not-a-real-token")
    assert response.status_code == 404


def test_convert_requires_accepted_status(client, db_session):
    owner = make_org_with_owner(db_session, email="owner6@example.com")
    draft_quote = make_quote(db_session, owner.organization, owner.user)

    response = client.post(
        f"/organizations/{owner.organization.id}/quotes/{draft_quote.id}/convert",
        headers=owner.auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "quote_not_accepted"


def test_convert_is_one_time_only(client, db_session):
    owner = make_org_with_owner(db_session, email="owner7@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)
    _mark_sent(db_session, quote)
    quote.status = QuoteStatus.accepted.value
    db_session.commit()

    first = client.post(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}/convert",
        headers=owner.auth_headers,
    )
    assert first.status_code == 200

    second = client.post(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}/convert",
        headers=owner.auth_headers,
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "quote_already_converted"


def test_quote_snapshot_immune_to_later_product_edits(client, db_session):
    """Editing a product after a quote referencing it was created must
    never change the quote's already-stored description/unit_price --
    those are a snapshot taken at creation time, not a live join."""
    owner = make_org_with_owner(db_session, email="owner8@example.com")
    product = make_product(db_session, owner.organization, name="Widget", unit_price=Decimal("25.00"))

    from app.schemas import QuoteLineItemCreate

    quote = make_quote(
        db_session,
        owner.organization,
        owner.user,
        line_items=[
            QuoteLineItemCreate(
                description="Widget", quantity=Decimal("1"), unit_price=Decimal("25.00"), product_id=product.id
            )
        ],
    )
    original_line_total = quote.line_items[0].line_total

    product.name = "Renamed Widget"
    product.default_unit_price = Decimal("999.00")
    db_session.commit()

    db_session.refresh(quote)
    assert quote.line_items[0].description == "Widget"
    assert quote.line_items[0].unit_price == Decimal("25.00")
    assert quote.line_items[0].line_total == original_line_total


def test_invoice_from_converted_quote_immune_to_later_quote_edits(client, db_session):
    """Editing the quote's notes/customer after conversion must never
    reach the invoice it produced -- convert_quote_to_invoice creates
    fresh, independent InvoiceLineItem rows."""
    owner = make_org_with_owner(db_session, email="owner9@example.com")
    quote = make_quote(db_session, owner.organization, owner.user, notes="Original notes")
    _mark_sent(db_session, quote)
    quote.status = QuoteStatus.accepted.value
    db_session.commit()

    response = client.post(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}/convert",
        headers=owner.auth_headers,
    )
    assert response.status_code == 200
    invoice_id = response.json()["invoice_id"]

    quote.notes = "Changed after conversion"
    db_session.commit()

    from app.models import Invoice

    invoice = db_session.query(Invoice).filter_by(id=invoice_id).one()
    assert invoice.line_items[0].description == quote.line_items[0].description
    # The invoice has its own independent line item rows -- never the
    # same primary keys as the quote's.
    assert invoice.line_items[0].id != quote.line_items[0].id
