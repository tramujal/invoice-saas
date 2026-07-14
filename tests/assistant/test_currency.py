"""AI Agent currency inference/validation for create_invoice_draft and
create_quote_draft -- mirrors the direct HTTP behavior in
tests/invoices/test_invoice_currency.py and tests/quotes/test_quote_currency.py,
plus checks the proposal summary shown to the user matches what execute()
actually persists (build_proposal and execute() independently compute
currency; a regression here would mean the two silently drift)."""

import json

from app.ai.base import ToolInvocation
from tests.factories import make_customer, make_org_with_owner, make_product


def _ndjson_events(response_text: str) -> list[dict]:
    return [json.loads(line) for line in response_text.strip().splitlines() if line]


def _chat(client, org_id, headers, message="do it"):
    response = client.post(
        f"/organizations/{org_id}/assistant/chat",
        json={"message": message},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return _ndjson_events(response.text)


def test_ai_create_invoice_draft_infers_currency_from_product(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner1@example.com")
    customer = make_customer(db_session, owner.organization)
    product = make_product(db_session, owner.organization, name="Hosting", currency_code="EUR")
    fake_ai_provider.events = [
        ToolInvocation(
            name="create_invoice_draft",
            arguments={
                "customer_name": customer.name,
                "line_items": [{"product_name": "Hosting"}],
            },
        )
    ]

    events = _chat(client, owner.organization.id, owner.auth_headers)
    proposals = [e for e in events if e["type"] == "action_proposal"]
    assert len(proposals) == 1, events
    # The proposal preview must show the *inferred* currency, not the org
    # default -- build_proposal computes this via the same resolver
    # execute() uses, closing a pre-existing drift bug.
    assert proposals[0]["summary"]["currency_code"] == "EUR"

    confirm = client.post(
        f"/organizations/{owner.organization.id}/assistant/actions/{proposals[0]['proposal_id']}/confirm",
        headers=owner.auth_headers,
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["summary"]["currency_code"] == "EUR"


def test_ai_create_invoice_draft_requires_currency_for_manual_line(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner2@example.com")
    customer = make_customer(db_session, owner.organization)
    fake_ai_provider.events = [
        ToolInvocation(
            name="create_invoice_draft",
            arguments={
                "customer_name": customer.name,
                "line_items": [{"description": "One-off consulting", "unit_price": "50.00"}],
            },
        )
    ]

    events = _chat(client, owner.organization.id, owner.auth_headers)
    assert any(e["type"] == "error" and e["code"] == "currency_required" for e in events), events


def test_ai_create_quote_draft_infers_currency_from_product(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner3@example.com")
    customer = make_customer(db_session, owner.organization)
    product = make_product(db_session, owner.organization, name="Support", currency_code="UYU")
    fake_ai_provider.events = [
        ToolInvocation(
            name="create_quote_draft",
            arguments={
                "customer_name": customer.name,
                "line_items": [{"product_name": "Support"}],
            },
        )
    ]

    events = _chat(client, owner.organization.id, owner.auth_headers)
    proposals = [e for e in events if e["type"] == "action_proposal"]
    assert len(proposals) == 1, events
    assert proposals[0]["summary"]["currency_code"] == "UYU"

    confirm = client.post(
        f"/organizations/{owner.organization.id}/assistant/actions/{proposals[0]['proposal_id']}/confirm",
        headers=owner.auth_headers,
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["summary"]["currency_code"] == "UYU"


def test_ai_create_quote_draft_requires_currency_for_manual_line(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner4@example.com")
    customer = make_customer(db_session, owner.organization)
    fake_ai_provider.events = [
        ToolInvocation(
            name="create_quote_draft",
            arguments={
                "customer_name": customer.name,
                "line_items": [{"description": "One-off consulting", "unit_price": "50.00"}],
            },
        )
    ]

    events = _chat(client, owner.organization.id, owner.auth_headers)
    assert any(e["type"] == "error" and e["code"] == "currency_required" for e in events), events
