"""Phase 23 -- the experimental WhatsApp assistant.

Covers: provider contracts (via FakeWhatsAppProvider), HMAC/signature +
replay protection, identity linking (code issue/verify/expiry/attempt
cap), RBAC + tenant isolation, removed-user access revocation, plan
gating + quota enforcement, read commands, mutation proposal + confirm/
cancel + idempotency, ambiguity, multi-turn context, voice/transcription,
invalid media, PDF send via background job, background-job retry
classification, and disabled/unconfigured-transport behavior.

No test requires a real WhatsApp account -- every provider boundary
(WhatsAppProvider, TranscriptionProvider, AIProvider) is faked; domain
services (ActionTool, plan_limits, permissions) are exercised for real.
"""

import base64
import json
import os
import time

import pytest

from app.ai.base import ChatMessage, TextDelta, ToolInvocation
from app.job_type import JobType
from app.jobs.handlers.whatsapp import WhatsAppSendDocumentPayload, handle_whatsapp_send_document
from app.jobs.registry import JobOutcome
from app.membership_role import MembershipRole
from app.models import BackgroundJob, WhatsAppIdentity, WhatsAppInboundMessage
from app.whatsapp import queries, service
from app.whatsapp.context_store import get_context_store
from app.whatsapp.provider_base import WhatsAppBridgeUnavailableError
from app.whatsapp.schemas import WhatsAppInboundEnvelope
from app.whatsapp.security import (
    hash_verification_code,
    normalize_phone_number,
    sign_bridge_request,
    verify_bridge_signature,
    InvalidBridgeSignatureError,
)
from app.whatsapp_identity_status import WhatsAppIdentityStatus
from tests.factories import make_customer, make_invoice, make_membership, make_org_with_owner_on_plan, make_user

os.environ.setdefault("WHATSAPP_BRIDGE_SECRET", "test-bridge-secret")
os.environ.setdefault("WHATSAPP_ENABLED", "true")
os.environ.setdefault("WHATSAPP_PROVIDER", "bridge")

PHONE = "+15551234567"


def _envelope(**overrides) -> WhatsAppInboundEnvelope:
    defaults = dict(
        provider="webjs",
        message_id="msg-1",
        phone_number=PHONE,
        timestamp="2026-01-01T00:00:00Z",
        type="text",
        text="ayuda",
    )
    defaults.update(overrides)
    return WhatsAppInboundEnvelope(**defaults)


def _whatsapp_org(db_session, **plan_overrides):
    defaults = dict(whatsapp_enabled=True, max_whatsapp_users=None, monthly_whatsapp_actions=None, ai_enabled=True)
    defaults.update(plan_overrides)
    return make_org_with_owner_on_plan(db_session, **defaults)


def _link_and_verify(db_session, organization_id, user, phone=PHONE):
    result = service.initiate_link(db_session, organization_id, user, phone)
    envelope = _envelope(phone_number=phone, message_id=f"verify-{phone}", text=result.verification_code)
    service.handle_inbound_message(db_session, envelope)
    return db_session.get(WhatsAppIdentity, result.identity_id)


# --- normalization / security ------------------------------------------------


def test_normalize_phone_number_strips_formatting_and_jid_suffix():
    assert normalize_phone_number("+598 (99) 123-456") == "+59899123456"
    assert normalize_phone_number("59899123456@c.us") == "+59899123456"
    assert normalize_phone_number("0059899123456") == "+59899123456"


def test_sign_and_verify_bridge_request_roundtrip():
    body = b'{"hello":"world"}'
    ts = int(time.time())
    header = sign_bridge_request(secret="s3cret", timestamp=ts, body=body)
    verify_bridge_signature(secret="s3cret", signature_header=header, body=body, tolerance_seconds=300)


def test_verify_bridge_signature_rejects_tampered_body():
    body = b'{"hello":"world"}'
    ts = int(time.time())
    header = sign_bridge_request(secret="s3cret", timestamp=ts, body=body)
    with pytest.raises(InvalidBridgeSignatureError):
        verify_bridge_signature(secret="s3cret", signature_header=header, body=b'{"hello":"tampered"}', tolerance_seconds=300)


def test_verify_bridge_signature_rejects_wrong_secret():
    body = b"payload"
    ts = int(time.time())
    header = sign_bridge_request(secret="s3cret", timestamp=ts, body=body)
    with pytest.raises(InvalidBridgeSignatureError):
        verify_bridge_signature(secret="different", signature_header=header, body=body, tolerance_seconds=300)


def test_verify_bridge_signature_rejects_stale_timestamp():
    body = b"payload"
    old_ts = int(time.time()) - 10_000
    header = sign_bridge_request(secret="s3cret", timestamp=old_ts, body=body)
    with pytest.raises(InvalidBridgeSignatureError):
        verify_bridge_signature(secret="s3cret", signature_header=header, body=body, tolerance_seconds=300)


def test_bridge_inbound_endpoint_requires_valid_signature(client, db_session):
    org = _whatsapp_org(db_session)
    body = json.dumps({"provider": "webjs", "message_id": "x", "phone_number": PHONE, "timestamp": "t", "type": "text", "text": "hola"}).encode()
    response = client.post(
        "/whatsapp/bridge/inbound",
        content=body,
        headers={"X-WhatsApp-Bridge-Signature": "t=1,v1=deadbeef"},
    )
    assert response.status_code == 401


def test_bridge_inbound_endpoint_accepts_correctly_signed_request(client, db_session):
    _whatsapp_org(db_session)
    body = json.dumps(
        {"provider": "webjs", "message_id": "sig-ok-1", "phone_number": PHONE, "timestamp": "t", "type": "text", "text": "ayuda"}
    ).encode()
    ts = int(time.time())
    header = sign_bridge_request(secret=os.environ["WHATSAPP_BRIDGE_SECRET"], timestamp=ts, body=body)
    response = client.post("/whatsapp/bridge/inbound", content=body, headers={"X-WhatsApp-Bridge-Signature": header})
    assert response.status_code == 200


# --- idempotency / replay -----------------------------------------------------


def test_duplicate_message_id_is_processed_only_once(db_session):
    owner = _whatsapp_org(db_session)
    identity = _link_and_verify(db_session, owner.organization.id, owner.user)

    envelope = _envelope(message_id="dup-1", text="ayuda")
    result_a = service.handle_inbound_message(db_session, envelope)
    result_b = service.handle_inbound_message(db_session, envelope)

    assert result_a["status"] == "processed"
    assert result_b["status"] == "duplicate"
    count = (
        db_session.query(WhatsAppInboundMessage)
        .filter_by(provider="webjs", message_id="dup-1")
        .count()
    )
    assert count == 1


# --- identity linking ---------------------------------------------------------


def test_initiate_link_issues_a_pending_identity_with_hashed_code(db_session):
    owner = _whatsapp_org(db_session)
    result = service.initiate_link(db_session, owner.organization.id, owner.user, PHONE)

    identity = db_session.get(WhatsAppIdentity, result.identity_id)
    assert identity.status == WhatsAppIdentityStatus.pending.value
    assert identity.verification_code_hash == hash_verification_code(result.verification_code)
    assert identity.verification_code_hash != result.verification_code


def test_correct_code_verifies_the_identity(db_session):
    owner = _whatsapp_org(db_session)
    identity = _link_and_verify(db_session, owner.organization.id, owner.user)
    assert identity.status == WhatsAppIdentityStatus.verified.value
    assert identity.verified_at is not None


def test_wrong_code_increments_attempts_and_never_verifies(db_session):
    owner = _whatsapp_org(db_session)
    result = service.initiate_link(db_session, owner.organization.id, owner.user, PHONE)

    envelope = _envelope(message_id="wrong-1", text="000000")
    service.handle_inbound_message(db_session, envelope)

    identity = db_session.get(WhatsAppIdentity, result.identity_id)
    assert identity.status == WhatsAppIdentityStatus.pending.value
    assert identity.verification_attempts == 1


def test_too_many_wrong_attempts_locks_out_the_pending_code(db_session):
    owner = _whatsapp_org(db_session)
    result = service.initiate_link(db_session, owner.organization.id, owner.user, PHONE)

    for i in range(6):
        service.handle_inbound_message(db_session, _envelope(message_id=f"wrong-{i}", text="000000"))

    identity = db_session.get(WhatsAppIdentity, result.identity_id)
    assert identity.status == WhatsAppIdentityStatus.pending.value
    # Even the CORRECT code no longer works once attempts are exhausted.
    service.handle_inbound_message(db_session, _envelope(message_id="late-correct", text=result.verification_code))
    db_session.refresh(identity)
    assert identity.status == WhatsAppIdentityStatus.pending.value


def test_expired_code_is_rejected(db_session):
    from datetime import datetime, timedelta, timezone

    owner = _whatsapp_org(db_session)
    result = service.initiate_link(db_session, owner.organization.id, owner.user, PHONE)
    identity = db_session.get(WhatsAppIdentity, result.identity_id)
    identity.verification_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    service.handle_inbound_message(db_session, _envelope(message_id="expired-1", text=result.verification_code))
    db_session.refresh(identity)
    assert identity.status == WhatsAppIdentityStatus.pending.value


def test_phone_already_verified_to_another_account_cannot_be_relinked(db_session):
    owner_a = _whatsapp_org(db_session, email="a-owner@example.com", org_name="Org A")
    owner_b = _whatsapp_org(db_session, email="b-owner@example.com", org_name="Org B")
    _link_and_verify(db_session, owner_a.organization.id, owner_a.user)

    with pytest.raises(service.PhoneAlreadyLinkedError):
        service.initiate_link(db_session, owner_b.organization.id, owner_b.user, PHONE)


def test_requesting_a_second_different_phone_reuses_the_pending_row_not_a_stray_second_one(db_session):
    """Regression test (found during Phase 23.1's live verification against
    the real backend): a user requesting a link for phone B while still
    pending on phone A used to silently create a SECOND live
    WhatsAppIdentity row for the same (org, user) -- queries
    .get_identity_for_user_in_org (used by GET .../whatsapp/me and
    self-revoke) has always assumed exactly one such row exists, and with
    two present its unordered db.scalar() could return either one,
    non-deterministically. initiate_link now reuses the user's own
    existing PENDING row instead of creating a competing one."""
    owner = _whatsapp_org(db_session)
    first = service.initiate_link(db_session, owner.organization.id, owner.user, "+15550001111")
    second = service.initiate_link(db_session, owner.organization.id, owner.user, "+15550002222")

    assert second.identity_id == first.identity_id, "a second row was created instead of reusing the pending one"

    rows = db_session.query(WhatsAppIdentity).filter(WhatsAppIdentity.user_id == owner.user.id).all()
    assert len(rows) == 1
    assert rows[0].normalized_phone_number == "+15550002222"

    resolved = queries.get_identity_for_user_in_org(db_session, owner.organization.id, owner.user.id)
    assert resolved.normalized_phone_number == "+15550002222"


def test_requesting_a_different_phone_while_verified_requires_explicit_revoke_first(db_session):
    """Same bug, the other half: once the user's own identity is VERIFIED
    (not just pending), it must never be silently repurposed by a second
    link request -- that would swap out an already-active security
    identity without the explicit revoke this phase's confirmation-first
    posture requires everywhere else."""
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user, phone="+15550003333")

    with pytest.raises(service.PhoneAlreadyLinkedError):
        service.initiate_link(db_session, owner.organization.id, owner.user, "+15550004444")

    identity = queries.get_identity_for_user_in_org(db_session, owner.organization.id, owner.user.id)
    assert identity.normalized_phone_number == "+15550003333"
    assert identity.status == WhatsAppIdentityStatus.verified.value


def test_unlinked_phone_gets_a_generic_not_linked_reply(db_session, fake_whatsapp_provider):
    service.handle_inbound_message(db_session, _envelope(message_id="unknown-1", phone_number="+19998887777", text="ayuda"))
    assert len(fake_whatsapp_provider.sent_text) == 1
    assert fake_whatsapp_provider.sent_text[0][0] == "+19998887777"


# --- RBAC / tenant isolation / removed-user access ---------------------------


def test_identity_never_resolves_across_organizations(db_session):
    owner_a = _whatsapp_org(db_session, email="iso-a@example.com", org_name="Iso A")
    owner_b = _whatsapp_org(db_session, email="iso-b@example.com", org_name="Iso B")
    identity_a = _link_and_verify(db_session, owner_a.organization.id, owner_a.user, phone="+15559990001")
    identity_b = _link_and_verify(db_session, owner_b.organization.id, owner_b.user, phone="+15559990002")

    assert identity_a.organization_id == owner_a.organization.id
    assert identity_b.organization_id == owner_b.organization.id
    assert identity_a.id != identity_b.id


def test_disabled_user_immediately_loses_whatsapp_access(db_session, fake_whatsapp_provider):
    from app.user_status import UserStatus

    owner = _whatsapp_org(db_session)
    identity = _link_and_verify(db_session, owner.organization.id, owner.user)

    owner.user.status = UserStatus.disabled.value
    db_session.commit()

    service.handle_inbound_message(db_session, _envelope(message_id="after-disable-1", text="ayuda"))
    last_message = fake_whatsapp_provider.sent_text[-1][1]
    assert "access" in last_message.lower() or "acceso" in last_message.lower()

    row = db_session.query(WhatsAppInboundMessage).filter_by(message_id="after-disable-1").one()
    assert row.status == "rejected_inactive"


def test_removed_membership_immediately_loses_whatsapp_access(db_session, fake_whatsapp_provider):
    owner = _whatsapp_org(db_session)
    identity = _link_and_verify(db_session, owner.organization.id, owner.user)

    membership = (
        db_session.query(type(owner.membership))
        .filter_by(user_id=owner.user.id, organization_id=owner.organization.id)
        .one()
    )
    from app.membership_status import MembershipStatus

    membership.status = MembershipStatus.removed.value
    db_session.commit()

    service.handle_inbound_message(db_session, _envelope(message_id="after-removal-1", text="ayuda"))
    row = db_session.query(WhatsAppInboundMessage).filter_by(message_id="after-removal-1").one()
    assert row.status == "rejected_inactive"


# --- plan gating / quota ------------------------------------------------------


def test_link_request_itself_is_blocked_when_plan_lacks_whatsapp(db_session):
    from app.billing.enforcement import CapabilityDeniedError

    owner = _whatsapp_org(db_session, whatsapp_enabled=False)
    with pytest.raises(CapabilityDeniedError):
        service.initiate_link(db_session, owner.organization.id, owner.user, PHONE)


def test_plan_downgrade_after_linking_rejects_further_messages(db_session, fake_whatsapp_provider):
    """A realistic scenario: the org was on a WhatsApp-enabled plan when
    the user linked their phone, then got downgraded -- every check in
    the inbound pipeline is re-derived live, so access is revoked on the
    very next message, with no separate step needed."""
    owner = _whatsapp_org(db_session)
    identity = _link_and_verify(db_session, owner.organization.id, owner.user)

    from app.services.entitlements import get_active_subscription
    from app.models import Plan

    subscription = get_active_subscription(db_session, owner.organization.id)
    plan = db_session.get(Plan, subscription.plan_id)
    plan.whatsapp_enabled = False
    db_session.commit()

    service.handle_inbound_message(db_session, _envelope(message_id="plan-off-1", text="ayuda"))
    row = db_session.query(WhatsAppInboundMessage).filter_by(message_id="plan-off-1").one()
    assert row.status == "plan_restricted"


def test_whatsapp_actions_quota_blocks_further_messages(db_session, fake_whatsapp_provider):
    owner = _whatsapp_org(db_session, monthly_whatsapp_actions=1)
    _link_and_verify(db_session, owner.organization.id, owner.user)

    r1 = service.handle_inbound_message(db_session, _envelope(message_id="quota-1", text="ayuda"))
    r2 = service.handle_inbound_message(db_session, _envelope(message_id="quota-2", text="ayuda"))

    row2 = db_session.query(WhatsAppInboundMessage).filter_by(message_id="quota-2").one()
    assert row2.status == "plan_limit_reached"


def test_whatsapp_users_quota_blocks_verification_not_link_request(db_session):
    owner = _whatsapp_org(db_session, max_whatsapp_users=0)
    result = service.initiate_link(db_session, owner.organization.id, owner.user, PHONE)
    # Link request itself succeeds (a pending row doesn't consume a seat).
    assert result.status == "pending"

    service.handle_inbound_message(db_session, _envelope(message_id="seat-1", text=result.verification_code))
    identity = db_session.get(WhatsAppIdentity, result.identity_id)
    # Verification is blocked by the zero-seat quota.
    assert identity.status == WhatsAppIdentityStatus.pending.value


# --- read commands -------------------------------------------------------------


def test_help_command_replies_without_touching_the_ai_provider(db_session, fake_whatsapp_provider, fake_ai_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)

    service.handle_inbound_message(db_session, _envelope(message_id="help-1", text="ayuda"))

    assert len(fake_ai_provider.calls) == 0
    assert len(fake_whatsapp_provider.sent_text) >= 1


def test_forget_context_clears_pending_proposal(db_session, fake_whatsapp_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)
    get_context_store().set_pending_proposal(owner.organization.id, owner.user.id, "some-proposal-id")

    service.handle_inbound_message(db_session, _envelope(message_id="forget-1", text="olvidar contexto"))

    context = get_context_store().get(owner.organization.id, owner.user.id)
    assert context.pending_proposal_id is None


# --- mutation proposal / confirm / cancel / idempotency -----------------------


def _script_create_invoice_proposal(fake_ai_provider, customer_name: str):
    fake_ai_provider.events = [
        ToolInvocation(
            name="create_invoice_draft",
            arguments={
                "customer_name": customer_name,
                "line_items": [{"description": "Web design", "unit_price": "1200.00"}],
                "currency_code": "USD",
            },
        )
    ]


def test_mutating_command_creates_a_proposal_not_an_invoice(db_session, fake_whatsapp_provider, fake_ai_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)
    customer = make_customer(db_session, owner.organization, name="Juan Perez")
    _script_create_invoice_proposal(fake_ai_provider, "Juan Perez")

    service.handle_inbound_message(db_session, _envelope(message_id="propose-1", text="Crea una factura para Juan Perez por USD 1200 por diseno web"))

    context = get_context_store().get(owner.organization.id, owner.user.id)
    assert context.pending_proposal_id is not None
    reply_text = fake_whatsapp_provider.sent_text[-1][1]
    assert "CONFIRM" in reply_text.upper()

    from app.models import Invoice

    assert db_session.query(Invoice).filter_by(organization_id=owner.organization.id).count() == 0


def test_confirmar_executes_the_pending_proposal_exactly_once(db_session, fake_whatsapp_provider, fake_ai_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)
    make_customer(db_session, owner.organization, name="Juan Perez")
    _script_create_invoice_proposal(fake_ai_provider, "Juan Perez")

    service.handle_inbound_message(db_session, _envelope(message_id="propose-2", text="Crea una factura para Juan Perez por USD 1200 por diseno web"))
    service.handle_inbound_message(db_session, _envelope(message_id="confirm-1", text="CONFIRMAR"))
    service.handle_inbound_message(db_session, _envelope(message_id="confirm-2", text="confirmar"))

    from app.models import Invoice

    invoices = db_session.query(Invoice).filter_by(organization_id=owner.organization.id).all()
    assert len(invoices) == 1

    row2 = db_session.query(WhatsAppInboundMessage).filter_by(message_id="confirm-2").one()
    assert row2.failure_code == "no_pending_action"


def test_cancelar_cancels_without_executing(db_session, fake_whatsapp_provider, fake_ai_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)
    make_customer(db_session, owner.organization, name="Juan Perez")
    _script_create_invoice_proposal(fake_ai_provider, "Juan Perez")

    service.handle_inbound_message(db_session, _envelope(message_id="propose-3", text="Crea una factura para Juan Perez por USD 1200"))
    service.handle_inbound_message(db_session, _envelope(message_id="cancel-1", text="CANCELAR"))

    from app.models import Invoice

    assert db_session.query(Invoice).filter_by(organization_id=owner.organization.id).count() == 0


def test_another_phone_cannot_confirm_someone_elses_proposal(db_session, fake_ai_provider):
    """The pending-proposal id lives in a context keyed by (org, user) --
    a different user's phone in the same org has its own, empty context,
    so CONFIRMAR from them finds nothing to act on."""
    owner = _whatsapp_org(db_session)
    other_user = make_user(db_session, email="other@example.com")
    make_membership(db_session, other_user, owner.organization, role=MembershipRole.member)
    _link_and_verify(db_session, owner.organization.id, owner.user, phone="+15551110001")
    _link_and_verify(db_session, owner.organization.id, other_user, phone="+15551110002")

    make_customer(db_session, owner.organization, name="Juan Perez")
    _script_create_invoice_proposal(fake_ai_provider, "Juan Perez")
    service.handle_inbound_message(
        db_session, _envelope(message_id="p1", phone_number="+15551110001", text="Crea una factura para Juan Perez")
    )

    service.handle_inbound_message(db_session, _envelope(message_id="c1", phone_number="+15551110002", text="CONFIRMAR"))
    row = db_session.query(WhatsAppInboundMessage).filter_by(message_id="c1").one()
    assert row.failure_code == "no_pending_action"


# --- ambiguity -----------------------------------------------------------------


def test_ambiguous_customer_never_creates_a_proposal(db_session, fake_whatsapp_provider, fake_ai_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)
    make_customer(db_session, owner.organization, name="Acme Inc")
    make_customer(db_session, owner.organization, name="Acme Corp")
    fake_ai_provider.events = [
        ToolInvocation(name="create_invoice_draft", arguments={"customer_name": "Acme", "line_items": [{"description": "x", "unit_price": "1"}]})
    ]

    service.handle_inbound_message(db_session, _envelope(message_id="ambig-1", text="Crea una factura para Acme"))

    context = get_context_store().get(owner.organization.id, owner.user.id)
    assert context.pending_proposal_id is None
    reply = fake_whatsapp_provider.sent_text[-1][1]
    assert "Acme Inc" in reply and "Acme Corp" in reply


# --- multi-turn context ---------------------------------------------------------


def test_conversation_history_carries_across_turns(db_session, fake_ai_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)

    fake_ai_provider.events = [TextDelta(text="Hola, ¿en qué te ayudo?")]
    service.handle_inbound_message(db_session, _envelope(message_id="turn-1", text="Hola"))

    fake_ai_provider.events = [TextDelta(text="Claro.")]
    service.handle_inbound_message(db_session, _envelope(message_id="turn-2", text="Segundo mensaje"))

    second_call_messages = fake_ai_provider.calls[-1][1]
    contents = [m.content for m in second_call_messages]
    assert "Hola" in contents
    assert "Segundo mensaje" in contents


# --- voice / transcription -------------------------------------------------------


def test_voice_message_is_transcribed_and_replied_with_transcript(
    db_session, fake_whatsapp_provider, fake_transcription_provider, fake_ai_provider
):
    owner = _whatsapp_org(db_session, voice_messages_enabled=True)
    _link_and_verify(db_session, owner.organization.id, owner.user)
    fake_transcription_provider.transcript = "cuanto facture este mes"
    fake_ai_provider.events = [TextDelta(text="Facturaste USD 0.")]

    audio_b64 = base64.b64encode(b"fake-ogg-bytes").decode()
    envelope = _envelope(
        message_id="voice-1",
        type="audio",
        text="",
        media={"mime_type": "audio/ogg", "size_bytes": len(b"fake-ogg-bytes"), "content_base64": audio_b64},
    )
    service.handle_inbound_message(db_session, envelope)

    all_replies = " ".join(text for _phone, text in fake_whatsapp_provider.sent_text)
    assert "cuanto facture este mes" in all_replies
    assert "Facturaste USD 0." in all_replies


def test_voice_message_without_transcription_configured_gives_honest_error(db_session, fake_whatsapp_provider):
    owner = _whatsapp_org(db_session, voice_messages_enabled=True)
    _link_and_verify(db_session, owner.organization.id, owner.user)
    # fake_transcription_provider fixture not requested -- default
    # FakeTranscriptionProvider() has no scripted transcript, so it raises.

    audio_b64 = base64.b64encode(b"x").decode()
    envelope = _envelope(
        message_id="voice-2", type="audio", text="",
        media={"mime_type": "audio/ogg", "size_bytes": 1, "content_base64": audio_b64},
    )
    service.handle_inbound_message(db_session, envelope)
    row = db_session.query(WhatsAppInboundMessage).filter_by(message_id="voice-2").one()
    assert row.status == "failed"


def test_voice_plan_restriction_is_distinct_from_transport_restriction(db_session, fake_whatsapp_provider):
    owner = _whatsapp_org(db_session, voice_messages_enabled=False)
    _link_and_verify(db_session, owner.organization.id, owner.user)

    envelope = _envelope(
        message_id="voice-3", type="audio", text="",
        media={"mime_type": "audio/ogg", "size_bytes": 1, "content_base64": "eA=="},
    )
    service.handle_inbound_message(db_session, envelope)
    row = db_session.query(WhatsAppInboundMessage).filter_by(message_id="voice-3").one()
    assert row.status == "plan_restricted"


def test_oversized_audio_is_rejected_before_transcription(db_session, fake_transcription_provider):
    owner = _whatsapp_org(db_session, voice_messages_enabled=True)
    _link_and_verify(db_session, owner.organization.id, owner.user)

    envelope = _envelope(
        message_id="voice-4", type="audio", text="",
        media={"mime_type": "audio/ogg", "size_bytes": 999_999_999, "content_base64": "eA=="},
    )
    service.handle_inbound_message(db_session, envelope)
    assert len(fake_transcription_provider.calls) == 0
    row = db_session.query(WhatsAppInboundMessage).filter_by(message_id="voice-4").one()
    assert row.failure_code == "audio_too_large"


def test_invalid_audio_mime_type_is_rejected(db_session, fake_transcription_provider):
    owner = _whatsapp_org(db_session, voice_messages_enabled=True)
    _link_and_verify(db_session, owner.organization.id, owner.user)

    envelope = _envelope(
        message_id="voice-5", type="audio", text="",
        media={"mime_type": "application/octet-stream", "size_bytes": 1, "content_base64": "eA=="},
    )
    service.handle_inbound_message(db_session, envelope)
    assert len(fake_transcription_provider.calls) == 0


# --- PDF send via background job -------------------------------------------------


def test_send_invoice_command_enqueues_a_document_job(db_session, fake_whatsapp_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)
    customer = make_customer(db_session, owner.organization)
    invoice = make_invoice(db_session, owner.organization, owner.user, customer=customer)
    from app.invoice_numbering import format_invoice_number

    number = format_invoice_number(invoice.invoice_number)

    service.handle_inbound_message(db_session, _envelope(message_id="send-doc-1", text=f"Mandame la factura {number}"))

    job = db_session.query(BackgroundJob).filter_by(job_type=JobType.whatsapp_send_document.value).one()
    payload = json.loads(job.payload)
    assert payload["document_id"] == invoice.id


def test_send_document_job_calls_the_provider_and_succeeds(db_session, fake_whatsapp_provider):
    owner = _whatsapp_org(db_session)
    customer = make_customer(db_session, owner.organization)
    invoice = make_invoice(db_session, owner.organization, owner.user, customer=customer)

    payload = WhatsAppSendDocumentPayload(
        document_type="invoice", document_id=invoice.id, phone_number=PHONE, document_number="INV-000001"
    )
    job = BackgroundJob(organization_id=owner.organization.id, job_type=JobType.whatsapp_send_document.value, payload="{}")
    result = handle_whatsapp_send_document(db_session, job, payload)

    assert result.outcome == JobOutcome.succeeded
    assert len(fake_whatsapp_provider.sent_documents) == 1
    assert fake_whatsapp_provider.sent_documents[0][0] == PHONE


def test_send_document_job_missing_document_is_permanently_failed(db_session):
    payload = WhatsAppSendDocumentPayload(
        document_type="invoice", document_id="does-not-exist", phone_number=PHONE, document_number="INV-000999"
    )
    job = BackgroundJob(organization_id="org-x", job_type=JobType.whatsapp_send_document.value, payload="{}")
    result = handle_whatsapp_send_document(db_session, job, payload)
    assert result.outcome == JobOutcome.permanently_failed
    assert result.error_code == "document_missing"


def test_send_document_job_retries_on_bridge_unavailable(db_session, fake_whatsapp_provider, monkeypatch):
    owner = _whatsapp_org(db_session)
    customer = make_customer(db_session, owner.organization)
    invoice = make_invoice(db_session, owner.organization, owner.user, customer=customer)

    def _raise(*a, **kw):
        raise WhatsAppBridgeUnavailableError("down")

    monkeypatch.setattr(fake_whatsapp_provider, "send_document", _raise)

    payload = WhatsAppSendDocumentPayload(
        document_type="invoice", document_id=invoice.id, phone_number=PHONE, document_number="INV-000001"
    )
    job = BackgroundJob(organization_id=owner.organization.id, job_type=JobType.whatsapp_send_document.value, payload="{}")
    result = handle_whatsapp_send_document(db_session, job, payload)
    assert result.outcome == JobOutcome.retry


def test_document_not_found_replies_honestly(db_session, fake_whatsapp_provider):
    owner = _whatsapp_org(db_session)
    _link_and_verify(db_session, owner.organization.id, owner.user)

    service.handle_inbound_message(db_session, _envelope(message_id="send-doc-2", text="Mandame la factura INV-999999"))
    reply = fake_whatsapp_provider.sent_text[-1][1]
    assert "999999" not in reply  # no raw internal detail leaked
    row = db_session.query(WhatsAppInboundMessage).filter_by(message_id="send-doc-2").one()
    assert row.status == "processed"


# --- disabled / unconfigured transport ------------------------------------------


def test_null_provider_status_is_disconnected_and_never_raises():
    from app.whatsapp.null_provider import NullWhatsAppProvider
    from app.whatsapp.provider_base import WhatsAppConnectionState

    provider = NullWhatsAppProvider()
    status_ = provider.get_connection_status()
    assert status_.state == WhatsAppConnectionState.disconnected


def test_null_provider_send_raises_not_configured():
    from app.whatsapp.null_provider import NullWhatsAppProvider
    from app.whatsapp.provider_base import WhatsAppNotConfiguredError as NotConfigured

    provider = NullWhatsAppProvider()
    with pytest.raises(NotConfigured):
        provider.send_text_message(PHONE, "hi")


def test_provider_factory_returns_null_when_transport_disabled(monkeypatch):
    from app.whatsapp.provider_factory import get_whatsapp_provider
    from app.whatsapp.null_provider import NullWhatsAppProvider

    monkeypatch.setenv("WHATSAPP_ENABLED", "false")
    assert isinstance(get_whatsapp_provider(), NullWhatsAppProvider)
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")


def test_provider_factory_returns_null_when_bridge_env_missing(monkeypatch):
    from app.whatsapp.provider_factory import get_whatsapp_provider
    from app.whatsapp.null_provider import NullWhatsAppProvider

    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "bridge")
    monkeypatch.delenv("WHATSAPP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("WHATSAPP_BRIDGE_SECRET", raising=False)
    assert isinstance(get_whatsapp_provider(), NullWhatsAppProvider)


# --- settings REST surface (HTTP) -----------------------------------------------


def test_status_endpoint_requires_org_membership(client, db_session):
    owner_a = _whatsapp_org(db_session, email="rest-a@example.com", org_name="Rest A")
    owner_b = _whatsapp_org(db_session, email="rest-b@example.com", org_name="Rest B")
    response = client.get(f"/organizations/{owner_a.organization.id}/whatsapp/status", headers=owner_b.auth_headers)
    assert response.status_code == 403


def test_link_then_admin_revoke_flow(client, db_session):
    owner = _whatsapp_org(db_session)
    link_response = client.post(
        f"/organizations/{owner.organization.id}/whatsapp/link",
        json={"phone_number": PHONE},
        headers=owner.auth_headers,
    )
    assert link_response.status_code == 200
    identity_id = link_response.json()["identity_id"]

    revoke_response = client.post(
        f"/organizations/{owner.organization.id}/whatsapp/identities/{identity_id}/revoke",
        headers=owner.auth_headers,
    )
    assert revoke_response.status_code == 204

    identity = db_session.get(WhatsAppIdentity, identity_id)
    assert identity.status == WhatsAppIdentityStatus.disabled.value


def test_identities_list_requires_settings_manage(client, db_session):
    from app.security import create_access_token

    owner = _whatsapp_org(db_session)
    member = make_user(db_session, email="viewer@example.com")
    make_membership(db_session, member, owner.organization, role=MembershipRole.viewer)

    response = client.get(
        f"/organizations/{owner.organization.id}/whatsapp/identities",
        headers={"Authorization": f"Bearer {create_access_token(member.id)}"},
    )
    assert response.status_code == 403
