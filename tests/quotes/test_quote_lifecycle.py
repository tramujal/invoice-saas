from decimal import Decimal

import pytest

from app.quote_status import QuoteStatus
from app.webhook_event_type import WebhookEventType
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
            "currency_code": "USD",
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


def test_public_accept_reject_blocked_for_suspended_organization(client, db_session):
    from app.organization_status import OrganizationStatus

    owner = make_org_with_owner(db_session, email="owner-suspended@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)
    _mark_sent(db_session, quote)
    owner.organization.status = OrganizationStatus.suspended.value
    db_session.commit()

    accept = client.post(f"/quotes/public/{quote.public_token}/accept")
    assert accept.status_code == 409
    assert accept.json()["detail"]["code"] == "organization_suspended"

    reject = client.post(f"/quotes/public/{quote.public_token}/reject")
    assert reject.status_code == 409
    assert reject.json()["detail"]["code"] == "organization_suspended"

    db_session.refresh(quote)
    assert quote.status == QuoteStatus.sent.value


def test_public_quote_view_and_pdf_remain_available_for_suspended_organization(client, db_session):
    from app.organization_status import OrganizationStatus

    owner = make_org_with_owner(db_session, email="owner-suspended2@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)
    _mark_sent(db_session, quote)
    owner.organization.status = OrganizationStatus.suspended.value
    db_session.commit()

    view = client.get(f"/quotes/public/{quote.public_token}")
    assert view.status_code == 200

    pdf = client.get(f"/quotes/public/{quote.public_token}/pdf")
    assert pdf.status_code == 200


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


def test_update_rejected_for_accepted_quote(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-immutable-accepted@example.com")
    quote = make_quote(db_session, owner.organization, owner.user, notes="Original notes")
    _mark_sent(db_session, quote)
    quote.status = QuoteStatus.accepted.value
    db_session.commit()

    response = client.patch(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}",
        json={"notes": "Trying to sneak an edit in"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "quote_not_editable"

    db_session.refresh(quote)
    assert quote.notes == "Original notes"


def test_update_rejected_for_rejected_quote(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-immutable-rejected@example.com")
    quote = make_quote(db_session, owner.organization, owner.user, notes="Original notes")
    _mark_sent(db_session, quote)
    quote.status = QuoteStatus.rejected.value
    db_session.commit()

    response = client.patch(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}",
        json={"notes": "Trying to sneak an edit in"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "quote_not_editable"


def test_update_rejected_for_converted_quote(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-immutable-converted@example.com")
    quote = make_quote(db_session, owner.organization, owner.user, notes="Original notes")
    _mark_sent(db_session, quote)
    quote.status = QuoteStatus.accepted.value
    db_session.commit()

    convert = client.post(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}/convert",
        headers=owner.auth_headers,
    )
    assert convert.status_code == 200

    response = client.patch(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}",
        json={"notes": "Trying to sneak an edit in"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "quote_not_editable"


def test_update_still_allowed_for_draft_and_sent_quotes(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-still-editable@example.com")
    draft_quote = make_quote(db_session, owner.organization, owner.user, notes="Draft notes")

    draft_response = client.patch(
        f"/organizations/{owner.organization.id}/quotes/{draft_quote.id}",
        json={"notes": "Edited draft notes"},
        headers=owner.auth_headers,
    )
    assert draft_response.status_code == 200
    assert draft_response.json()["notes"] == "Edited draft notes"

    sent_quote = make_quote(db_session, owner.organization, owner.user, notes="Sent notes")
    _mark_sent(db_session, sent_quote)

    sent_response = client.patch(
        f"/organizations/{owner.organization.id}/quotes/{sent_quote.id}",
        json={"notes": "Edited sent notes"},
        headers=owner.auth_headers,
    )
    assert sent_response.status_code == 200
    assert sent_response.json()["notes"] == "Edited sent notes"


def test_quote_customer_snapshot_immune_to_later_customer_edits(client, db_session):
    owner = make_org_with_owner(db_session, email="owner-quote-snapshot@example.com")
    customer = make_customer(db_session, owner.organization, name="Original Name", email="original@example.com")
    customer.phone = "555-0000"
    customer.address = "1 Original St"
    db_session.commit()

    quote = make_quote(db_session, owner.organization, owner.user, customer=customer)

    customer.name = "Renamed Customer"
    customer.email = "renamed@example.com"
    customer.phone = "555-9999"
    customer.address = "2 Renamed Ave"
    db_session.commit()

    response = client.get(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}", headers=owner.auth_headers
    )
    assert response.status_code == 200
    assert response.json()["customer_name"] == "Original Name"

    db_session.refresh(quote)
    assert quote.customer_name_snapshot == "Original Name"
    assert quote.customer_email_snapshot == "original@example.com"
    assert quote.customer_phone_snapshot == "555-0000"
    assert quote.customer_address_snapshot == "1 Original St"


def test_converted_invoice_forwards_quotes_own_snapshot_not_customers_current_state(client, db_session):
    """A customer edited AFTER a quote was created but BEFORE it's later
    converted must still produce an invoice reflecting the quote's own
    original snapshot -- not the customer's state at conversion time."""
    owner = make_org_with_owner(db_session, email="owner-convert-snapshot@example.com")
    customer = make_customer(db_session, owner.organization, name="Original Name", email="original@example.com")

    quote = make_quote(db_session, owner.organization, owner.user, customer=customer)
    _mark_sent(db_session, quote)
    quote.status = QuoteStatus.accepted.value
    db_session.commit()

    # Customer edited between quote creation and conversion.
    customer.name = "Edited Before Conversion"
    customer.email = "edited@example.com"
    db_session.commit()

    response = client.post(
        f"/organizations/{owner.organization.id}/quotes/{quote.id}/convert",
        headers=owner.auth_headers,
    )
    assert response.status_code == 200
    invoice_id = response.json()["invoice_id"]

    from app.models import Invoice

    invoice = db_session.query(Invoice).filter_by(id=invoice_id).one()
    assert invoice.customer_name_snapshot == "Original Name"
    assert invoice.customer_email_snapshot == "original@example.com"


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


def test_convert_interrupted_before_shared_commit_leaves_neither_invoice_nor_quote_change(
    client, db_session, monkeypatch
):
    """Phase P2.2 (H4): create_invoice_record(commit=False) inside
    convert_quote_to_invoice no longer commits on its own -- the invoice
    creation and the quote's own status/converted_invoice_id update share
    ONE commit at the end of convert_quote_to_invoice. Simulates a crash
    in that window (after the invoice's own writes are queued, before
    the shared commit) by making the quote.converted emit_event call
    raise -- db.rollback() (what a real request's session teardown does
    implicitly on an unhandled exception, see app.database.get_db) must
    discard BOTH the queued invoice AND the queued quote update, not just
    one of them."""
    from app.models import Invoice
    from app.services import quotes as quotes_service

    owner = make_org_with_owner(db_session, email="owner-atomic@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)
    _mark_sent(db_session, quote)
    quote.status = QuoteStatus.accepted.value
    db_session.commit()

    original_emit_event = quotes_service.emit_event

    def _raise_on_quote_converted(db, *, event_type, **kwargs):
        if event_type == WebhookEventType.quote_converted:
            raise RuntimeError("simulated crash before the shared commit")
        return original_emit_event(db, event_type=event_type, **kwargs)

    monkeypatch.setattr(quotes_service, "emit_event", _raise_on_quote_converted)

    with pytest.raises(RuntimeError):
        quotes_service.convert_quote_to_invoice(db_session, owner.organization.id, quote, owner.user)

    db_session.rollback()

    assert db_session.query(Invoice).filter_by(organization_id=owner.organization.id).count() == 0
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.accepted.value
    assert quote.converted_invoice_id is None


def test_convert_retry_after_interruption_creates_exactly_one_invoice(client, db_session, monkeypatch):
    """Directly continues test_convert_interrupted_before_shared_commit_...
    -- once the transaction that failed has been rolled back, the SAME
    quote must still be convertible, and retrying must produce exactly
    one invoice. Before this fix (create_invoice_record's own internal
    commit persisting the invoice independently of the quote update), a
    genuine crash in this window would have left a committed invoice
    with no converted_invoice_id recorded, so this same retry would have
    created a SECOND invoice for one quote."""
    from app.models import Invoice
    from app.services import quotes as quotes_service

    owner = make_org_with_owner(db_session, email="owner-atomic-retry@example.com")
    quote = make_quote(db_session, owner.organization, owner.user)
    _mark_sent(db_session, quote)
    quote.status = QuoteStatus.accepted.value
    db_session.commit()

    original_emit_event = quotes_service.emit_event
    call_count = {"n": 0}

    def _raise_once_on_quote_converted(db, *, event_type, **kwargs):
        if event_type == WebhookEventType.quote_converted and call_count["n"] == 0:
            call_count["n"] += 1
            raise RuntimeError("simulated crash on first attempt only")
        return original_emit_event(db, event_type=event_type, **kwargs)

    monkeypatch.setattr(quotes_service, "emit_event", _raise_once_on_quote_converted)

    with pytest.raises(RuntimeError):
        quotes_service.convert_quote_to_invoice(db_session, owner.organization.id, quote, owner.user)
    db_session.rollback()

    # Retry: the same quote, still un-converted, now succeeds for real.
    result = quotes_service.convert_quote_to_invoice(db_session, owner.organization.id, quote, owner.user)

    assert db_session.query(Invoice).filter_by(organization_id=owner.organization.id).count() == 1
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.converted.value
    assert quote.converted_invoice_id == result.invoice.id
