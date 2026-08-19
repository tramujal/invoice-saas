"""Phase 29 -- HTTP surface, permissions, tenant isolation, events, and
the analytics/receivables/forecasting integration.
"""

from decimal import Decimal

import pytest

from app.adjustment_note_status import AdjustmentNoteStatus
from app.models import AdjustmentNote, AuditEntry, WebhookEvent
from app.schemas import InvoiceLineItemCreate
from app.membership_role import MembershipRole
from tests.factories import (
    make_customer,
    make_invoice,
    make_member_in_org,
    make_org_with_owner,
)


def inv_line(desc, qty, price, rate="0"):
    return InvoiceLineItemCreate(
        description=desc, quantity=Decimal(qty), unit_price=Decimal(price), tax_rate=Decimal(rate)
    )


@pytest.fixture
def setup(db_session):
    owner = make_org_with_owner(db_session, email="api-notes@example.com", org_name="API Notes Co")
    customer = make_customer(db_session, owner.organization, email="c@example.com")
    invoice = make_invoice(
        db_session,
        owner.organization,
        owner.user,
        customer=customer,
        line_items=[
            inv_line("A", "1", "1000.00", "0.22"),
            inv_line("B", "1", "500.00", "0.10"),
            inv_line("C", "1", "200.00", "0"),
        ],
        tax_rate=Decimal("0"),
    )
    return owner, invoice


def base(owner):
    return f"/organizations/{owner.organization.id}"


def create(client, owner, invoice, note_type, lines, **body):
    return client.post(
        f"{base(owner)}/invoices/{invoice.id}/adjustment-notes/{note_type}",
        json={"line_items": lines, **body},
        headers=owner.auth_headers,
    )


LINE_500 = [{"description": "Partial refund", "quantity": "1", "unit_price": "500.00", "tax_rate": "0.22"}]


# --- create / read ----------------------------------------------------


def test_create_credit_note(client, db_session, setup):
    owner, invoice = setup
    r = create(client, owner, invoice, "credit", LINE_500)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["note_number"] == "CN-000001"
    assert body["note_type"] == "credit"
    assert body["status"] == "draft"
    assert body["total"] == "610.00"  # 500 + 22%
    assert body["currency_code"] == invoice.currency_code
    assert body["source_invoice_id"] == invoice.id
    assert [(g["rate"], g["base"], g["tax"]) for g in body["tax_groups"]] == [
        ("0.2200", "500.00", "110.00")
    ]


def test_create_debit_note(client, db_session, setup):
    owner, invoice = setup
    r = create(
        client,
        owner,
        invoice,
        "debit",
        [{"description": "Omitted delivery", "quantity": "1", "unit_price": "100.00", "tax_rate": "0.22"}],
    )
    assert r.status_code == 201, r.text
    assert r.json()["note_number"] == "DN-000001"
    assert r.json()["total"] == "122.00"


def test_creditability_endpoint_prefills_a_form(client, db_session, setup):
    owner, invoice = setup
    r = client.get(f"{base(owner)}/invoices/{invoice.id}/creditability", headers=owner.auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["original_total"] == "1970.00"
    assert body["summary"]["remaining_creditable"] == "1970.00"
    assert len(body["lines"]) == 3
    assert body["lines"][0]["remaining_creditable"] == "1000.00"
    assert body["lines"][0]["tax_rate"] == "0.2200"


def test_issue_then_list_and_get(client, db_session, setup):
    owner, invoice = setup
    note_id = create(client, owner, invoice, "credit", LINE_500).json()["id"]

    issued = client.post(f"{base(owner)}/adjustment-notes/{note_id}/issue", headers=owner.auth_headers)
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "issued"
    assert issued.json()["issue_date"] is not None

    listing = client.get(f"{base(owner)}/adjustment-notes", headers=owner.auth_headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == note_id

    one = client.get(f"{base(owner)}/adjustment-notes/{note_id}", headers=owner.auth_headers)
    assert one.status_code == 200
    assert one.json()["note_number"] == "CN-000001"


def test_list_filters_by_type_and_status(client, db_session, setup):
    owner, invoice = setup
    credit_id = create(client, owner, invoice, "credit", LINE_500).json()["id"]
    create(client, owner, invoice, "debit", [{"description": "X", "quantity": "1", "unit_price": "10.00"}])
    client.post(f"{base(owner)}/adjustment-notes/{credit_id}/issue", headers=owner.auth_headers)

    by_type = client.get(f"{base(owner)}/adjustment-notes?note_type=debit", headers=owner.auth_headers).json()
    assert by_type["total"] == 1 and by_type["items"][0]["note_type"] == "debit"

    by_status = client.get(f"{base(owner)}/adjustment-notes?status=issued", headers=owner.auth_headers).json()
    assert by_status["total"] == 1 and by_status["items"][0]["id"] == credit_id


def test_notes_for_invoice_includes_drafts_and_voids(client, db_session, setup):
    owner, invoice = setup
    note_id = create(client, owner, invoice, "credit", LINE_500).json()["id"]
    client.post(f"{base(owner)}/adjustment-notes/{note_id}/issue", headers=owner.auth_headers)
    client.post(f"{base(owner)}/adjustment-notes/{note_id}/void", headers=owner.auth_headers)
    create(client, owner, invoice, "credit", LINE_500)

    rows = client.get(
        f"{base(owner)}/invoices/{invoice.id}/adjustment-notes", headers=owner.auth_headers
    ).json()
    assert {r["status"] for r in rows} == {"void", "draft"}


# --- over-credit over HTTP --------------------------------------------


def test_over_credit_returns_409_with_the_remaining_amount(client, db_session, setup):
    owner, invoice = setup
    first = create(
        client, owner, invoice, "credit",
        [{"description": "Most of it", "quantity": "1", "unit_price": "1900.00"}],
    ).json()
    client.post(f"{base(owner)}/adjustment-notes/{first['id']}/issue", headers=owner.auth_headers)

    r = create(client, owner, invoice, "credit", [{"description": "Too much", "quantity": "1", "unit_price": "100.00"}])
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "over_credit"
    assert detail["remaining_creditable"] == "70.00"


def test_line_over_credit_returns_409(client, db_session, setup):
    """Deliberately stays INSIDE the document ceiling, so this can only be
    the line-level rule firing: line A (1000) is fully credited, then a
    further 100 against it is requested while 750 still remains
    creditable on the invoice as a whole."""
    owner, invoice = setup
    line_a = invoice.line_items[0].id
    full = [{"description": "A", "quantity": "1", "unit_price": "1000.00", "tax_rate": "0.22",
             "source_invoice_line_item_id": line_a}]
    first = create(client, owner, invoice, "credit", full).json()
    client.post(f"{base(owner)}/adjustment-notes/{first['id']}/issue", headers=owner.auth_headers)

    summary = client.get(
        f"{base(owner)}/invoices/{invoice.id}/creditability", headers=owner.auth_headers
    ).json()["summary"]
    assert summary["remaining_creditable"] == "750.00"  # document ceiling is NOT the constraint

    r = create(client, owner, invoice, "credit",
               [{"description": "A again", "quantity": "1", "unit_price": "100.00",
                 "tax_rate": "0.22", "source_invoice_line_item_id": line_a}])
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "line_over_credit"


def test_debit_line_referencing_an_invoice_line_is_422(client, db_session, setup):
    owner, invoice = setup
    r = create(
        client, owner, invoice, "debit",
        [{"description": "X", "quantity": "1", "unit_price": "10.00",
          "source_invoice_line_item_id": invoice.line_items[0].id}],
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "debit_line_cannot_reference_source"


def test_free_form_line_without_a_price_is_rejected(client, db_session, setup):
    owner, invoice = setup
    r = create(client, owner, invoice, "credit", [{"description": "No price", "quantity": "1"}])
    assert r.status_code == 422


# --- lifecycle over HTTP ----------------------------------------------


def test_issued_notes_cannot_be_deleted_only_voided(client, db_session, setup):
    owner, invoice = setup
    note_id = create(client, owner, invoice, "credit", LINE_500).json()["id"]
    client.post(f"{base(owner)}/adjustment-notes/{note_id}/issue", headers=owner.auth_headers)

    deleted = client.delete(f"{base(owner)}/adjustment-notes/{note_id}", headers=owner.auth_headers)
    assert deleted.status_code == 409
    assert deleted.json()["detail"]["code"] == "note_not_draft"

    voided = client.post(f"{base(owner)}/adjustment-notes/{note_id}/void", headers=owner.auth_headers)
    assert voided.status_code == 200
    assert db_session.get(AdjustmentNote, note_id) is not None


def test_draft_notes_can_be_deleted(client, db_session, setup):
    owner, invoice = setup
    note_id = create(client, owner, invoice, "credit", LINE_500).json()["id"]
    assert client.delete(f"{base(owner)}/adjustment-notes/{note_id}", headers=owner.auth_headers).status_code == 204
    assert db_session.get(AdjustmentNote, note_id) is None


# --- permissions and tenant isolation ---------------------------------


def test_viewer_can_read_but_not_create(client, db_session, setup):
    owner, invoice = setup
    viewer = make_member_in_org(db_session, owner.organization, email="viewer@example.com", role=MembershipRole.viewer)

    r = client.get(f"{base(owner)}/adjustment-notes", headers=viewer.auth_headers)
    assert r.status_code == 200

    denied = client.post(
        f"{base(owner)}/invoices/{invoice.id}/adjustment-notes/credit",
        json={"line_items": LINE_500},
        headers=viewer.auth_headers,
    )
    assert denied.status_code == 403


def test_member_can_create(client, db_session, setup):
    owner, invoice = setup
    member = make_member_in_org(db_session, owner.organization, email="member@example.com", role=MembershipRole.member)
    r = client.post(
        f"{base(owner)}/invoices/{invoice.id}/adjustment-notes/credit",
        json={"line_items": LINE_500},
        headers=member.auth_headers,
    )
    assert r.status_code == 201, r.text


def test_cross_tenant_access_is_impossible(client, db_session, setup):
    owner, invoice = setup
    outsider = make_org_with_owner(db_session, email="outsider@example.com", org_name="Outsider Co")
    note_id = create(client, owner, invoice, "credit", LINE_500).json()["id"]

    # Reading another tenant's note through one's own org path.
    assert client.get(
        f"/organizations/{outsider.organization.id}/adjustment-notes/{note_id}",
        headers=outsider.auth_headers,
    ).status_code == 404

    # Creating a note against another tenant's invoice.
    assert client.post(
        f"/organizations/{outsider.organization.id}/invoices/{invoice.id}/adjustment-notes/credit",
        json={"line_items": LINE_500},
        headers=outsider.auth_headers,
    ).status_code == 404

    # And using one's own org id but someone else's credentials.
    assert client.get(
        f"{base(owner)}/adjustment-notes/{note_id}", headers=outsider.auth_headers
    ).status_code == 403


# --- events / audit / webhooks ----------------------------------------


def test_lifecycle_emits_events_through_the_canonical_path(client, db_session, setup):
    owner, invoice = setup
    note_id = create(client, owner, invoice, "credit", LINE_500).json()["id"]
    client.post(f"{base(owner)}/adjustment-notes/{note_id}/issue", headers=owner.auth_headers)
    client.post(f"{base(owner)}/adjustment-notes/{note_id}/void", headers=owner.auth_headers)

    events = [
        e.event_type
        for e in db_session.query(WebhookEvent).filter_by(organization_id=owner.organization.id).all()
    ]
    assert "adjustment_note.created" in events
    assert "adjustment_note.issued" in events
    assert "adjustment_note.voided" in events

    # emit_event fans out to the audit log too -- one canonical path, not
    # three independent calls.
    audit = db_session.query(AuditEntry).filter_by(organization_id=owner.organization.id).all()
    assert any(
        entry.resource_type == "adjustment_note" and entry.resource_id == note_id
        for entry in audit
    )


def test_webhook_payload_is_useful_and_pii_minimal(client, db_session, setup):
    owner, invoice = setup
    create(client, owner, invoice, "credit", LINE_500, reason="Customer returned two units")

    event = (
        db_session.query(WebhookEvent)
        .filter_by(organization_id=owner.organization.id, event_type="adjustment_note.created")
        .one()
    )
    payload = event.payload
    for key in ("note_id", "note_type", "note_number", "source_invoice_id", "status", "currency_code", "total"):
        assert key in payload, key
    # The user's free-text reason is never broadcast.
    assert "reason" not in payload
    assert "Customer returned" not in str(payload)


# --- analytics / receivables / forecasting ----------------------------


def test_receivables_reflect_issued_credit_notes(client, db_session, setup):
    from datetime import date, timedelta

    from app.financial_intelligence.queries import get_receivables_snapshot

    owner, invoice = setup
    as_of = date.today() + timedelta(days=1)
    before = get_receivables_snapshot(db_session, owner.organization.id, as_of=as_of)
    assert before[invoice.currency_code][0] == Decimal("1970.00")

    note_id = create(
        client, owner, invoice, "credit",
        [{"description": "Partial", "quantity": "1", "unit_price": "500.00"}],
    ).json()["id"]
    client.post(f"{base(owner)}/adjustment-notes/{note_id}/issue", headers=owner.auth_headers)

    after = get_receivables_snapshot(db_session, owner.organization.id, as_of=as_of)
    assert after[invoice.currency_code][0] == Decimal("1470.00")


def test_receivables_ignore_draft_and_void_notes(client, db_session, setup):
    from datetime import date, timedelta

    from app.financial_intelligence.queries import get_receivables_snapshot

    owner, invoice = setup
    as_of = date.today() + timedelta(days=1)

    draft = create(client, owner, invoice, "credit", [{"description": "D", "quantity": "1", "unit_price": "500.00"}]).json()
    snapshot = get_receivables_snapshot(db_session, owner.organization.id, as_of=as_of)
    assert snapshot[invoice.currency_code][0] == Decimal("1970.00")

    client.post(f"{base(owner)}/adjustment-notes/{draft['id']}/issue", headers=owner.auth_headers)
    client.post(f"{base(owner)}/adjustment-notes/{draft['id']}/void", headers=owner.auth_headers)
    snapshot = get_receivables_snapshot(db_session, owner.organization.id, as_of=as_of)
    assert snapshot[invoice.currency_code][0] == Decimal("1970.00")


def test_revenue_is_net_of_issued_notes(client, db_session, setup):
    from app.analytics.calculators.revenue import get_revenue_by_currency

    owner, invoice = setup
    assert get_revenue_by_currency(db_session, owner.organization.id)[invoice.currency_code] == Decimal("1970.00")

    c = create(client, owner, invoice, "credit", [{"description": "C", "quantity": "1", "unit_price": "500.00"}]).json()
    client.post(f"{base(owner)}/adjustment-notes/{c['id']}/issue", headers=owner.auth_headers)
    d = create(client, owner, invoice, "debit", [{"description": "D", "quantity": "1", "unit_price": "200.00"}]).json()
    client.post(f"{base(owner)}/adjustment-notes/{d['id']}/issue", headers=owner.auth_headers)

    revenue = get_revenue_by_currency(db_session, owner.organization.id)
    assert revenue[invoice.currency_code] == Decimal("1670.00")  # 1970 - 500 + 200


def test_forecasting_series_adjusts_the_source_invoice_month(client, db_session, setup):
    """Date semantics: the correction lands in the month of the SALE, not
    the month the note was issued."""
    from datetime import datetime, timezone

    from app.financial_intelligence.queries import get_monthly_revenue_series

    owner, invoice = setup
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    before = get_monthly_revenue_series(db_session, owner.organization.id, [month_start])
    assert before[0].invoiced == Decimal("1970.00")

    c = create(client, owner, invoice, "credit", [{"description": "C", "quantity": "1", "unit_price": "500.00"}]).json()
    client.post(f"{base(owner)}/adjustment-notes/{c['id']}/issue", headers=owner.auth_headers)

    after = get_monthly_revenue_series(db_session, owner.organization.id, [month_start])
    assert after[0].invoiced == Decimal("1470.00")
    # `collected` is untouched: a credit note is not a refund, and the
    # payment model cannot express one.
    assert after[0].collected == before[0].collected
