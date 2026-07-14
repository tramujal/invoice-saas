from app.invitation_tokens import hash_invitation_token
from app.models import OrganizationInvitation, OrganizationMember
from tests.factories import make_org_with_owner


def test_create_invitation_sends_email_and_stores_hashed_token(client, db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    org_id = owner.organization.id

    response = client.post(
        f"/organizations/{org_id}/invitations",
        json={"email": "invitee@example.com", "role": "member"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 201, response.text

    invitation = db_session.query(OrganizationInvitation).filter_by(email="invitee@example.com").one()
    assert invitation.token_hash != response.json()["id"]
    # The raw token never appears anywhere in the stored row -- only its
    # hash. We don't have the raw token here (never returned over HTTP),
    # so this just confirms the column holds a hash-shaped value, not an
    # obviously-reversible one, and that the email fake actually fired.
    assert len(invitation.token_hash) >= 32

    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "invitee@example.com"


def test_create_invitation_rejects_owner_role(client, db_session):
    owner = make_org_with_owner(db_session, email="owner2@example.com")
    response = client.post(
        f"/organizations/{owner.organization.id}/invitations",
        json={"email": "invitee2@example.com", "role": "owner"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 422


def test_create_invitation_rejects_duplicate_pending(client, db_session):
    owner = make_org_with_owner(db_session, email="owner3@example.com")
    org_id = owner.organization.id
    payload = {"email": "dupe@example.com", "role": "member"}

    first = client.post(f"/organizations/{org_id}/invitations", json=payload, headers=owner.auth_headers)
    assert first.status_code == 201

    second = client.post(f"/organizations/{org_id}/invitations", json=payload, headers=owner.auth_headers)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "invitation_already_pending"


def test_create_invitation_rejects_existing_active_member(client, db_session):
    owner = make_org_with_owner(db_session, email="owner4@example.com")
    org_id = owner.organization.id

    response = client.post(
        f"/organizations/{org_id}/invitations",
        json={"email": "owner4@example.com", "role": "member"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_member"


def test_viewer_cannot_create_invitation(client, db_session):
    from app.membership_role import MembershipRole
    from tests.factories import make_member_in_org

    owner = make_org_with_owner(db_session, email="owner5@example.com")
    viewer = make_member_in_org(
        db_session, owner.organization, email="viewer@example.com", role=MembershipRole.viewer
    )
    response = client.post(
        f"/organizations/{owner.organization.id}/invitations",
        json={"email": "someone@example.com", "role": "member"},
        headers=viewer.auth_headers,
    )
    assert response.status_code == 403


def test_resend_rotates_token_and_invalidates_old_one(client, db_session, fake_email_sender):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole

    owner = make_org_with_owner(db_session, email="owner6@example.com")
    invitation, old_raw_token = invite_member_record(
        db_session, owner.organization.id, "invitee6@example.com", InvitationRole.member, owner.membership
    )
    old_hash = invitation.token_hash

    response = client.post(
        f"/organizations/{owner.organization.id}/invitations/{invitation.id}/resend",
        headers=owner.auth_headers,
    )
    assert response.status_code == 200

    db_session.refresh(invitation)
    assert invitation.token_hash != old_hash

    old_token_lookup = client.get(f"/invitations/public/{old_raw_token}")
    assert old_token_lookup.status_code == 404


def test_cancel_invitation_hard_deletes(client, db_session):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole

    owner = make_org_with_owner(db_session, email="owner7@example.com")
    invitation, _ = invite_member_record(
        db_session, owner.organization.id, "invitee7@example.com", InvitationRole.member, owner.membership
    )

    response = client.delete(
        f"/organizations/{owner.organization.id}/invitations/{invitation.id}",
        headers=owner.auth_headers,
    )
    assert response.status_code == 204
    assert db_session.query(OrganizationInvitation).filter_by(id=invitation.id).first() is None


def test_accept_invitation_happy_path_creates_membership(client, db_session):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole
    from tests.factories import make_user
    from app.security import create_access_token

    owner = make_org_with_owner(db_session, email="owner8@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "newmember@example.com", InvitationRole.admin, owner.membership
    )
    invitee = make_user(db_session, email="newmember@example.com")
    invitee_headers = {"Authorization": f"Bearer {create_access_token(invitee.id)}"}

    response = client.post(f"/invitations/public/{raw_token}/accept", headers=invitee_headers)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"

    membership = (
        db_session.query(OrganizationMember)
        .filter_by(user_id=invitee.id, organization_id=owner.organization.id)
        .one()
    )
    assert membership.role == "admin"


def test_accept_invitation_wrong_email_is_rejected(client, db_session):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole
    from tests.factories import make_user
    from app.security import create_access_token

    owner = make_org_with_owner(db_session, email="owner9@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "intended@example.com", InvitationRole.member, owner.membership
    )
    wrong_user = make_user(db_session, email="wrong-person@example.com")
    wrong_headers = {"Authorization": f"Bearer {create_access_token(wrong_user.id)}"}

    response = client.post(f"/invitations/public/{raw_token}/accept", headers=wrong_headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "invitation_email_mismatch"


def test_accept_invitation_expired_is_rejected(client, db_session):
    from datetime import datetime, timedelta, timezone
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole
    from tests.factories import make_user
    from app.security import create_access_token

    owner = make_org_with_owner(db_session, email="owner10@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "late@example.com", InvitationRole.member, owner.membership
    )
    invitation.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    invitee = make_user(db_session, email="late@example.com")
    invitee_headers = {"Authorization": f"Bearer {create_access_token(invitee.id)}"}

    response = client.post(f"/invitations/public/{raw_token}/accept", headers=invitee_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invitation_expired"


def test_accept_invitation_already_accepted_is_rejected(client, db_session):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole
    from tests.factories import make_user
    from app.security import create_access_token

    owner = make_org_with_owner(db_session, email="owner11@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "onceonly@example.com", InvitationRole.member, owner.membership
    )
    invitee = make_user(db_session, email="onceonly@example.com")
    invitee_headers = {"Authorization": f"Bearer {create_access_token(invitee.id)}"}

    first = client.post(f"/invitations/public/{raw_token}/accept", headers=invitee_headers)
    assert first.status_code == 200

    second = client.post(f"/invitations/public/{raw_token}/accept", headers=invitee_headers)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "invitation_already_accepted"


def test_invitation_token_stored_hashed_not_raw(db_session):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole

    owner = make_org_with_owner(db_session, email="owner12@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "hashcheck@example.com", InvitationRole.member, owner.membership
    )
    assert invitation.token_hash != raw_token
    assert invitation.token_hash == hash_invitation_token(raw_token)
