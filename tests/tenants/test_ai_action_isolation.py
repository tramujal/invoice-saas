"""A proposed AI action is scoped to the exact (organization, user) pair
it was created for. Confirming/cancelling it through a different org's
URL -- even with a role that would otherwise permit assistant.execute --
must 404, never leak that the proposal exists or belong to it."""

from datetime import datetime, timedelta, timezone

from app.assistant_action_status import AssistantActionStatus
from app.models import AssistantAction
from tests.factories import make_org_with_owner


def _make_proposed_action(db, organization_id: str, user_id: str) -> AssistantAction:
    action = AssistantAction(
        organization_id=organization_id,
        user_id=user_id,
        action_name="update_invoice_status",
        input_payload="{}",
        summary="Test action",
        status=AssistantActionStatus.proposed.value,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def test_confirm_across_orgs_is_404(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-a@example.com", org_name="Org A")
    org_b = make_org_with_owner(db_session, email="owner-b@example.com", org_name="Org B")
    action = _make_proposed_action(db_session, org_a.organization.id, org_a.user.id)

    response = client.post(
        f"/organizations/{org_b.organization.id}/assistant/actions/{action.id}/confirm",
        headers=org_b.auth_headers,
    )
    assert response.status_code == 404


def test_confirm_by_different_user_in_same_org_is_404(client, db_session):
    from app.membership_role import MembershipRole
    from tests.factories import make_member_in_org

    org_a = make_org_with_owner(db_session, email="owner-c@example.com", org_name="Org C")
    other_member = make_member_in_org(
        db_session, org_a.organization, email="other@example.com", role=MembershipRole.admin
    )
    action = _make_proposed_action(db_session, org_a.organization.id, org_a.user.id)

    response = client.post(
        f"/organizations/{org_a.organization.id}/assistant/actions/{action.id}/confirm",
        headers=other_member.auth_headers,
    )
    assert response.status_code == 404


def test_cancel_across_orgs_is_404(client, db_session):
    org_a = make_org_with_owner(db_session, email="owner-d@example.com", org_name="Org D")
    org_b = make_org_with_owner(db_session, email="owner-e@example.com", org_name="Org E")
    action = _make_proposed_action(db_session, org_a.organization.id, org_a.user.id)

    response = client.post(
        f"/organizations/{org_b.organization.id}/assistant/actions/{action.id}/cancel",
        headers=org_b.auth_headers,
    )
    assert response.status_code == 404
