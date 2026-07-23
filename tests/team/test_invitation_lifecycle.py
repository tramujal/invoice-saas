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


def test_accept_invitation_blocked_for_suspended_organization(client, db_session):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole
    from app.organization_status import OrganizationStatus
    from tests.factories import make_user
    from app.security import create_access_token

    owner = make_org_with_owner(db_session, email="owner-suspended@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "invitee-suspended@example.com", InvitationRole.member, owner.membership
    )
    invitee = make_user(db_session, email="invitee-suspended@example.com")
    invitee_headers = {"Authorization": f"Bearer {create_access_token(invitee.id)}"}

    owner.organization.status = OrganizationStatus.suspended.value
    db_session.commit()

    response = client.post(f"/invitations/public/{raw_token}/accept", headers=invitee_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "organization_suspended"

    assert (
        db_session.query(OrganizationMember)
        .filter_by(user_id=invitee.id, organization_id=owner.organization.id)
        .first()
        is None
    )


def test_view_invitation_remains_available_for_suspended_organization(client, db_session):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole
    from app.organization_status import OrganizationStatus

    owner = make_org_with_owner(db_session, email="owner-suspended2@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "invitee-suspended2@example.com", InvitationRole.member, owner.membership
    )
    owner.organization.status = OrganizationStatus.suspended.value
    db_session.commit()

    response = client.get(f"/invitations/public/{raw_token}")
    assert response.status_code == 200


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


def test_stale_invitation_with_tampered_role_cannot_bypass_hierarchy(client, db_session):
    """A stale/tampered invitation row whose role isn't a recognized
    InvitationRole (e.g. hand-edited to "owner", which InvitationRole
    never permits) must never be blindly trusted at accept time -- it's
    rejected outright rather than materializing a membership with an
    unvalidated role."""
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole
    from tests.factories import make_user
    from app.security import create_access_token

    owner = make_org_with_owner(db_session, email="owner-stale@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "stale-invitee@example.com", InvitationRole.member, owner.membership
    )
    # Simulate a tampered/stale row -- bypasses InvitationCreateRequest's
    # schema validation entirely, which is exactly what accept-time
    # revalidation must guard against.
    invitation.role = "owner"
    db_session.commit()

    invitee = make_user(db_session, email="stale-invitee@example.com")
    invitee_headers = {"Authorization": f"Bearer {create_access_token(invitee.id)}"}

    response = client.post(f"/invitations/public/{raw_token}/accept", headers=invitee_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invitation_invalid"

    assert (
        db_session.query(OrganizationMember)
        .filter_by(user_id=invitee.id, organization_id=owner.organization.id)
        .first()
        is None
    )


def test_invitation_acceptance_never_creates_an_owner(client, db_session):
    """Explicit regression for the Phase 13D.1 pre-check: the ONLY path
    that can ever set role="owner" is the dedicated grant-ownership
    action (app.services.team.grant_ownership_record) -- invitation
    acceptance materializes whatever InvitationRole was on the
    invitation, which structurally excludes "owner" (see
    app.membership_role.InvitationRole's docstring), and this holds even
    for the highest role an invitation can legitimately carry (admin)."""
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole
    from tests.factories import make_user
    from app.security import create_access_token

    owner = make_org_with_owner(db_session, email="owner-never-owner@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "never-owner-invitee@example.com", InvitationRole.admin, owner.membership
    )
    invitee = make_user(db_session, email="never-owner-invitee@example.com")
    invitee_headers = {"Authorization": f"Bearer {create_access_token(invitee.id)}"}

    response = client.post(f"/invitations/public/{raw_token}/accept", headers=invitee_headers)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"

    membership = (
        db_session.query(OrganizationMember)
        .filter_by(user_id=invitee.id, organization_id=owner.organization.id)
        .one()
    )
    assert membership.role != "owner"
    assert membership.role == "admin"


def test_invitation_token_stored_hashed_not_raw(db_session):
    from app.services.team import invite_member_record
    from app.membership_role import InvitationRole

    owner = make_org_with_owner(db_session, email="owner12@example.com")
    invitation, raw_token = invite_member_record(
        db_session, owner.organization.id, "hashcheck@example.com", InvitationRole.member, owner.membership
    )
    assert invitation.token_hash != raw_token
    assert invitation.token_hash == hash_invitation_token(raw_token)
