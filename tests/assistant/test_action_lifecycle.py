"""AI Assistant propose -> confirm lifecycle. Uses the autouse
fake_ai_provider fixture (never a real model call) configured per-test to
emit a ToolInvocation, exactly like a real provider deciding to call a
tool. The single most important test here is
test_confirm_rechecks_permission_after_demotion: permission is checked
once at propose time and independently again at confirm time, specifically
to catch a role change that happened in between."""

import json

from app.ai.base import ToolInvocation
from app.assistant_action_status import AssistantActionStatus
from app.invoice_numbering import format_invoice_number
from app.membership_role import MembershipRole
from app.models import AssistantAction
from app.payment_status import PaymentStatus
from tests.factories import make_invoice, make_member_in_org, make_org_with_owner


def _ndjson_events(response_text: str) -> list[dict]:
    return [json.loads(line) for line in response_text.strip().splitlines() if line]


def _propose_update_status(client, org_id, headers, invoice_reference, new_status="paid"):
    response = client.post(
        f"/organizations/{org_id}/assistant/chat",
        json={"message": "mark this invoice paid"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    events = _ndjson_events(response.text)
    proposals = [e for e in events if e["type"] == "action_proposal"]
    assert len(proposals) == 1, events
    return proposals[0]


def test_propose_creates_action_row_without_executing(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user)
    fake_ai_provider.events = [
        ToolInvocation(
            name="update_invoice_status",
            arguments={
                "invoice_reference": format_invoice_number(invoice.invoice_number),
                "new_status": "paid",
            },
        )
    ]

    proposal = _propose_update_status(client, owner.organization.id, owner.auth_headers, invoice.id)
    action = db_session.query(AssistantAction).filter_by(id=proposal["proposal_id"]).one()
    assert action.status == AssistantActionStatus.proposed.value
    assert action.action_name == "update_invoice_status"

    db_session.refresh(invoice)
    assert invoice.payment_status == PaymentStatus.pending.value


def test_confirm_executes_the_action(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner2@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user)
    fake_ai_provider.events = [
        ToolInvocation(
            name="update_invoice_status",
            arguments={
                "invoice_reference": format_invoice_number(invoice.invoice_number),
                "new_status": "paid",
            },
        )
    ]
    proposal = _propose_update_status(client, owner.organization.id, owner.auth_headers, invoice.id)

    response = client.post(
        f"/organizations/{owner.organization.id}/assistant/actions/{proposal['proposal_id']}/confirm",
        headers=owner.auth_headers,
    )
    assert response.status_code == 200, response.text
    db_session.refresh(invoice)
    assert invoice.payment_status == PaymentStatus.paid.value


def test_confirm_is_not_repeatable(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner3@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user)
    fake_ai_provider.events = [
        ToolInvocation(
            name="update_invoice_status",
            arguments={
                "invoice_reference": format_invoice_number(invoice.invoice_number),
                "new_status": "paid",
            },
        )
    ]
    proposal = _propose_update_status(client, owner.organization.id, owner.auth_headers, invoice.id)
    confirm_url = f"/organizations/{owner.organization.id}/assistant/actions/{proposal['proposal_id']}/confirm"

    first = client.post(confirm_url, headers=owner.auth_headers)
    assert first.status_code == 200

    second = client.post(confirm_url, headers=owner.auth_headers)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "assistant_action_already_used"


def test_confirm_rejects_expired_proposal(client, db_session, fake_ai_provider):
    from datetime import datetime, timedelta, timezone

    owner = make_org_with_owner(db_session, email="owner4@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user)
    fake_ai_provider.events = [
        ToolInvocation(
            name="update_invoice_status",
            arguments={
                "invoice_reference": format_invoice_number(invoice.invoice_number),
                "new_status": "paid",
            },
        )
    ]
    proposal = _propose_update_status(client, owner.organization.id, owner.auth_headers, invoice.id)

    action = db_session.query(AssistantAction).filter_by(id=proposal["proposal_id"]).one()
    action.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    response = client.post(
        f"/organizations/{owner.organization.id}/assistant/actions/{proposal['proposal_id']}/confirm",
        headers=owner.auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "assistant_action_expired"


def test_confirm_rejects_cancelled_proposal(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner5@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user)
    fake_ai_provider.events = [
        ToolInvocation(
            name="update_invoice_status",
            arguments={
                "invoice_reference": format_invoice_number(invoice.invoice_number),
                "new_status": "paid",
            },
        )
    ]
    proposal = _propose_update_status(client, owner.organization.id, owner.auth_headers, invoice.id)
    base_url = f"/organizations/{owner.organization.id}/assistant/actions/{proposal['proposal_id']}"

    cancel = client.post(f"{base_url}/cancel", headers=owner.auth_headers)
    assert cancel.status_code == 200

    confirm = client.post(f"{base_url}/confirm", headers=owner.auth_headers)
    assert confirm.status_code == 409
    assert confirm.json()["detail"]["code"] == "assistant_action_already_used"


def test_viewer_tool_call_is_denied_as_stream_event_not_persisted(client, db_session, fake_ai_provider):
    owner = make_org_with_owner(db_session, email="owner6@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user)
    viewer = make_member_in_org(
        db_session, owner.organization, email="viewer@example.com", role=MembershipRole.viewer
    )
    fake_ai_provider.events = [
        ToolInvocation(
            name="update_invoice_status",
            arguments={
                "invoice_reference": format_invoice_number(invoice.invoice_number),
                "new_status": "paid",
            },
        )
    ]

    response = client.post(
        f"/organizations/{owner.organization.id}/assistant/chat",
        json={"message": "mark this invoice paid"},
        headers=viewer.auth_headers,
    )
    assert response.status_code == 200
    events = _ndjson_events(response.text)
    assert any(e["type"] == "error" and e["code"] == "permission_denied" for e in events)
    assert db_session.query(AssistantAction).count() == 0


def test_confirm_rechecks_permission_after_demotion(client, db_session, fake_ai_provider):
    """The single highest-value authorization test for the AI Agent:
    permission must be evaluated at execution (confirm) time, not frozen
    at propose time. A user who was an admin when they proposed an action
    must be blocked at confirm if they've since been demoted to viewer."""
    owner = make_org_with_owner(db_session, email="owner7@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user)
    admin = make_member_in_org(
        db_session, owner.organization, email="admin@example.com", role=MembershipRole.admin
    )
    fake_ai_provider.events = [
        ToolInvocation(
            name="update_invoice_status",
            arguments={
                "invoice_reference": format_invoice_number(invoice.invoice_number),
                "new_status": "paid",
            },
        )
    ]

    proposal = _propose_update_status(client, owner.organization.id, admin.auth_headers, invoice.id)

    # Demotion happens strictly between propose and confirm.
    admin.membership.role = MembershipRole.viewer.value
    db_session.commit()

    response = client.post(
        f"/organizations/{owner.organization.id}/assistant/actions/{proposal['proposal_id']}/confirm",
        headers=admin.auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"

    db_session.refresh(invoice)
    assert invoice.payment_status == PaymentStatus.pending.value

    # Blocked at the router's own require_permission(assistant_execute)
    # gate -- a viewer no longer holds assistant_execute at all, so
    # confirm never even reaches _load_locked_action/the tool's own
    # execution branch, and the proposal row is left untouched (still
    # confirmable later if the user is ever re-promoted, exactly like any
    # other unconsumed proposal).
    action = db_session.query(AssistantAction).filter_by(id=proposal["proposal_id"]).one()
    assert action.status == AssistantActionStatus.proposed.value
