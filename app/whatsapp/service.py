"""Orchestration layer for the experimental WhatsApp assistant (Phase 23).

This is the one place inbound WhatsApp messages are interpreted and
replied to -- it is a CHANNEL, not a second command engine: every
mutating or business-data operation is delegated to the exact same
app.ai.engine.run_chat_turn / app.services.assistant_actions.confirm_action
/ app.services.invoices.get_invoice_in_org / app.invoice_pdf.render_invoice_pdf
etc. that the browser app already uses. Nothing here queries a domain
table directly except the WhatsApp-specific ones (WhatsAppIdentity,
WhatsAppInboundMessage) via app.whatsapp.queries.

Every inbound message re-derives, from scratch, the full authorization
chain a browser request would already imply: verified linked identity,
active user, active membership, active organization, RBAC permission
(via the same TOOL_PERMISSIONS/check_permission the HTTP routers use),
plan capability, plan quota, and rate limits. A phone number is NEVER
itself authentication -- see WhatsAppIdentity's own docstring.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import AIProviderError, AIProviderTimeoutError, ChatMessage
from app.ai.engine import ActionProposalEvent, ClarificationEvent, ErrorEvent, TextDeltaEvent, run_chat_turn
from app.ai.factory import get_ai_provider
from app.ai.prompts import ASSISTANT_SYSTEM_PROMPT
from app.ai.tools.registry import tool_definitions
from app.assistant_context import build_business_context, format_business_context_as_text
from app.billing.enforcement import (
    CapabilityDeniedError,
    require_ai,
    require_whatsapp,
    require_whatsapp_voice_messages,
)
from app.deps import require_org_member
from app.invoice_numbering import format_invoice_number
from app.invoice_pdf import render_invoice_pdf
from app.job_type import JobType
from app.localization import get_language, t
from app.membership_role import MembershipRole
from app.models import Organization, OrganizationMember, User, WhatsAppIdentity
from app.permissions import ROLE_PERMISSIONS, Permission, check_permission
from app.quote_numbering import format_quote_number
from app.quote_pdf import render_quote_pdf
from app.rate_limit import RateLimitCheck, RateLimitRule, enforce_rate_limit
from app.services.assistant_actions import ASSISTANT_ACTION_CONFIRM_RULES, cancel_action, confirm_action
from app.services.background_jobs import enqueue_job
from app.services.invoices import InvoiceNotFoundError, get_invoice_in_org
from app.services.plan_limits import LimitedResource, PlanLimitExceededError, check_limit
from app.services.quotes import QuoteNotFoundError, get_quote_in_org
from app.transcription.factory import get_transcription_provider
from app.transcription.provider_base import TranscriptionError, TranscriptionNotConfiguredError
from app.whatsapp import queries
from app.whatsapp.config import (
    WHATSAPP_ALLOWED_AUDIO_MIME_TYPES,
    WHATSAPP_AUDIO_MAX_BYTES,
    WHATSAPP_MAX_VERIFICATION_ATTEMPTS,
    WHATSAPP_MESSAGE_MAX_LENGTH,
    WHATSAPP_VERIFICATION_CODE_TTL_MINUTES,
)
from app.whatsapp.context_store import get_context_store
from app.whatsapp.provider_base import WhatsAppNotConfiguredError, WhatsAppProviderError
from app.whatsapp.provider_factory import (
    get_whatsapp_provider,
    is_whatsapp_transport_configured,
    is_whatsapp_transport_enabled,
)
from app.whatsapp.schemas import WhatsAppInboundEnvelope
from app.whatsapp.security import (
    generate_verification_code,
    hash_verification_code,
    normalize_phone_number,
    verification_code_matches,
)
from app.whatsapp_identity_status import WhatsAppIdentityStatus

logger = logging.getLogger(__name__)

PROVIDER_NAME = "webjs"

WHATSAPP_LINK_REQUEST_RULES = (RateLimitRule(limit=5, window_seconds=3600),)
WHATSAPP_INBOUND_MESSAGE_RULES = (RateLimitRule(limit=30, window_seconds=3600),)
WHATSAPP_QR_REQUEST_RULES = (RateLimitRule(limit=10, window_seconds=3600),)
# Independent budgets from the HTTP chat endpoint's own
# ASSISTANT_ACTION_PROPOSE_RULES/ASSISTANT_CHAT_RULES -- a WhatsApp user
# and the same person's browser session never share a rate-limit bucket,
# by design (see app.rate_limit's own scope-naming convention).
WHATSAPP_ASSISTANT_CHAT_RULES = (RateLimitRule(limit=20, window_seconds=3600),)
WHATSAPP_ASSISTANT_ACTION_PROPOSE_RULES = (RateLimitRule(limit=10, window_seconds=3600),)

_CONFIRM_WORDS = {"confirmar", "confirm"}
_CANCEL_WORDS = {"cancelar", "cancel"}
_HELP_WORDS = {"ayuda", "help"}
_FORGET_WORDS = {"olvidar contexto", "forget context"}

_DOCUMENT_REQUEST_RE = re.compile(r"\b(INV|QUO)-?0*(\d+)\b", re.IGNORECASE)


class WhatsAppServiceError(Exception):
    code: str = "whatsapp_error"


class InvalidPhoneNumberError(WhatsAppServiceError):
    code = "invalid_phone_number"


class PhoneAlreadyLinkedError(WhatsAppServiceError):
    """Raised when the normalized phone number is already `verified` for
    a DIFFERENT (organization, user) -- see WhatsAppIdentity's own
    docstring for why this is a single, global uniqueness constraint in
    this experimental phase."""

    code = "phone_already_linked"


class IdentityNotFoundError(WhatsAppServiceError):
    code = "identity_not_found"


@dataclass(frozen=True)
class WhatsAppLinkResult:
    identity_id: str
    normalized_phone_number: str
    status: str
    verification_code: str
    verification_expires_at: datetime


def initiate_link(db: Session, organization_id: str, current_user: User, raw_phone_number: str) -> WhatsAppLinkResult:
    """Section 5 of the phase spec, step 3: "Backend creates a short-lived
    one-time code." Any active member may request a link for their OWN
    phone -- self-serve, not gated by settings.manage (only admin revoke
    of ANOTHER member's identity requires that permission -- see
    admin_revoke_identity below).

    Deliberately does NOT check the max_whatsapp_users quota here -- a
    `pending` row never occupies a seat (see
    app.services.organization_usage.count_whatsapp_users, which only
    counts `verified` rows); the quota is enforced at the moment
    verification actually succeeds (see _try_handle_verification_code),
    which is when a seat is genuinely consumed."""
    require_org_member(current_user, organization_id, db)
    require_whatsapp(db, organization_id)

    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="whatsapp:link_request:user",
                identity=f"user:{current_user.id}",
                rules=WHATSAPP_LINK_REQUEST_RULES,
            )
        ]
    )

    normalized = normalize_phone_number(raw_phone_number)
    if len(normalized) < 8:
        raise InvalidPhoneNumberError("Phone number is too short to be valid.")

    existing = queries.get_any_identity_by_phone(db, PROVIDER_NAME, normalized)
    if existing is not None and existing.status == WhatsAppIdentityStatus.verified.value:
        if existing.organization_id == organization_id and existing.user_id == current_user.id:
            # Already linked to this exact account -- nothing to do, but
            # not an error either; re-issuing a fresh code is harmless.
            pass
        else:
            raise PhoneAlreadyLinkedError("This phone number is already linked to another account.")

    now = datetime.now(timezone.utc)
    code = generate_verification_code()

    if existing is not None:
        # Reusing/overwriting a PENDING (never verified) row regardless of
        # who created it is safe: a pending row never granted anyone
        # access -- the real security boundary is verification, which
        # only the actual owner of this physical phone can ever complete
        # (by sending the code FROM that WhatsApp number). See this
        # module's own docstring above for the full reasoning.
        identity = existing
        identity.organization_id = organization_id
        identity.user_id = current_user.id
    else:
        # A user may only ever have ONE current (pending or verified)
        # WhatsApp identity per organization -- queries
        # .get_identity_for_user_in_org (used by GET .../whatsapp/me and
        # self-revoke) has always assumed exactly that, singular, "current"
        # row. Nothing enforced it here: requesting a link for a second,
        # different phone number used to just create a second live row,
        # after which that query's unordered db.scalar() would silently
        # return an arbitrary one of them -- the wrong identity could be
        # shown, or revoked, without any error. Reusing the user's own
        # existing PENDING row mirrors the phone-collision reuse above (a
        # pending row never granted access); an existing VERIFIED row must
        # be revoked explicitly first, same as a phone verified elsewhere.
        own_existing = queries.get_identity_for_user_in_org(db, organization_id, current_user.id)
        if own_existing is not None and own_existing.status == WhatsAppIdentityStatus.verified.value:
            raise PhoneAlreadyLinkedError(
                "You already have a verified WhatsApp number linked. Revoke it before linking a different one."
            )
        if own_existing is not None:
            identity = own_existing
            identity.normalized_phone_number = normalized
        else:
            identity = WhatsAppIdentity(
                provider=PROVIDER_NAME,
                organization_id=organization_id,
                user_id=current_user.id,
                normalized_phone_number=normalized,
            )
            db.add(identity)

    identity.status = WhatsAppIdentityStatus.pending.value
    identity.verification_code_hash = hash_verification_code(code)
    identity.verification_expires_at = now + timedelta(minutes=WHATSAPP_VERIFICATION_CODE_TTL_MINUTES)
    identity.verification_attempts = 0
    db.commit()
    db.refresh(identity)

    return WhatsAppLinkResult(
        identity_id=identity.id,
        normalized_phone_number=identity.normalized_phone_number,
        status=identity.status,
        verification_code=code,
        verification_expires_at=identity.verification_expires_at,
    )


def revoke_own_identity(db: Session, organization_id: str, current_user: User, identity_id: str) -> None:
    require_org_member(current_user, organization_id, db)
    identity = queries.get_identity_in_org(db, organization_id, identity_id)
    if identity is None or identity.user_id != current_user.id:
        raise IdentityNotFoundError(identity_id)
    identity.status = WhatsAppIdentityStatus.disabled.value
    db.commit()
    get_context_store().forget(organization_id, current_user.id)


def admin_revoke_identity(db: Session, organization_id: str, identity_id: str) -> None:
    """Caller (app.routers.whatsapp) has already required settings.manage
    -- this function itself performs no permission check, matching how
    app.services.customers etc. trust their router to have gated access
    (the router IS the enforcement point; this is pure data mutation)."""
    identity = queries.get_identity_in_org(db, organization_id, identity_id)
    if identity is None:
        raise IdentityNotFoundError(identity_id)
    identity.status = WhatsAppIdentityStatus.disabled.value
    db.commit()
    get_context_store().forget(organization_id, identity.user_id)


def request_qr_code(db: Session, organization_id: str, current_user: User):
    require_org_member(current_user, organization_id, db)
    enforce_rate_limit(
        [RateLimitCheck(scope="whatsapp:qr_request:user", identity=f"user:{current_user.id}", rules=WHATSAPP_QR_REQUEST_RULES)]
    )
    return get_whatsapp_provider().request_qr_code()


# --- inbound message pipeline ------------------------------------------------


def _reply(phone_number: str, text: str) -> None:
    try:
        get_whatsapp_provider().send_text_message(phone_number, text[: WHATSAPP_MESSAGE_MAX_LENGTH * 4])
    except (WhatsAppProviderError, WhatsAppNotConfiguredError):
        logger.warning("whatsapp_service: failed to send outbound reply")


def _record(
    db: Session,
    *,
    message_id: str,
    organization_id: str | None,
    user_id: str | None,
    whatsapp_identity_id: str | None,
    message_type: str,
    command_action: str | None,
    status: str,
    failure_code: str | None = None,
) -> None:
    queries.record_inbound_message(
        db,
        provider=PROVIDER_NAME,
        message_id=message_id,
        organization_id=organization_id,
        user_id=user_id,
        whatsapp_identity_id=whatsapp_identity_id,
        message_type=message_type,
        command_action=command_action,
        status=status,
        failure_code=failure_code,
    )


def _try_handle_verification_code(
    db: Session, normalized_phone: str, envelope: WhatsAppInboundEnvelope
) -> bool:
    """Section 5, steps 4-8: the phone has no VERIFIED identity yet --
    check whether there's a pending one and the message looks like its
    code. Returns True if a pending identity existed at all (handled,
    whether the code matched or not) so the caller doesn't also send the
    generic "not linked" message."""
    pending = queries.get_any_identity_by_phone(db, PROVIDER_NAME, normalized_phone)
    if pending is None or pending.status != WhatsAppIdentityStatus.pending.value:
        return False

    organization = db.get(Organization, pending.organization_id)
    language = get_language(organization)
    candidate = envelope.text.strip()
    now = datetime.now(timezone.utc)

    expires_at = pending.verification_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if (
        pending.verification_attempts >= WHATSAPP_MAX_VERIFICATION_ATTEMPTS
        or expires_at is None
        or now > expires_at
        or not pending.verification_code_hash
        or not verification_code_matches(candidate, pending.verification_code_hash)
    ):
        pending.verification_attempts += 1
        db.commit()
        if pending.verification_attempts >= WHATSAPP_MAX_VERIFICATION_ATTEMPTS:
            _reply(normalized_phone, t(language, "whatsapp_link_too_many_attempts"))
        else:
            _reply(normalized_phone, t(language, "whatsapp_link_expired_or_invalid"))
        return True

    # Correct code -- but the whatsapp_users seat is only truly consumed
    # now, at verification time (see initiate_link's own docstring for why
    # a pending row never counted against it).
    try:
        check_limit(db, pending.organization_id, LimitedResource.whatsapp_users)
    except PlanLimitExceededError:
        _reply(normalized_phone, t(language, "whatsapp_quota_exceeded"))
        return True

    pending.status = WhatsAppIdentityStatus.verified.value
    pending.verified_at = now
    pending.verification_code_hash = None
    pending.verification_expires_at = None
    pending.verification_attempts = 0
    db.commit()
    _reply(normalized_phone, t(language, "whatsapp_link_confirmed"))
    return True


def _match_document_request(text: str) -> tuple[str, str] | None:
    match = _DOCUMENT_REQUEST_RE.search(text)
    if match is None:
        return None
    kind = "invoice" if match.group(1).upper() == "INV" else "quote"
    return kind, match.group(2)


def _handle_document_send(
    db: Session,
    identity: WhatsAppIdentity,
    caller_role: MembershipRole,
    kind: str,
    reference: str,
    normalized_phone: str,
    language: str,
) -> str:
    required = Permission.invoice_read if kind == "invoice" else Permission.quote_read
    if not check_permission(caller_role, required):
        return t(language, "whatsapp_document_not_found")

    try:
        if kind == "invoice":
            document = get_invoice_in_org(db, identity.organization_id, reference)
            document_number = format_invoice_number(document.invoice_number)
        else:
            document = get_quote_in_org(db, identity.organization_id, reference)
            document_number = format_quote_number(document.quote_number)
    except (InvoiceNotFoundError, QuoteNotFoundError):
        return t(language, "whatsapp_document_not_found")

    enqueue_job(
        db,
        job_type=JobType.whatsapp_send_document,
        payload={
            "document_type": kind,
            "document_id": document.id,
            "phone_number": normalized_phone,
            "document_number": document_number,
        },
        organization_id=identity.organization_id,
        idempotency_key=f"whatsapp-send-document:{kind}:{document.id}:{normalized_phone}",
    )
    return t(language, "whatsapp_document_sent")


def _format_error_code(code: str, language: str) -> str:
    known = {
        "permission_denied": "whatsapp_generic_error",
        "assistant_action_invalid": "whatsapp_generic_error",
        "plan_limit_reached": "whatsapp_quota_exceeded",
        "rate_limit_exceeded": "whatsapp_generic_error",
    }
    return t(language, known.get(code, "whatsapp_generic_error"))


def handle_inbound_message(db: Session, envelope: WhatsAppInboundEnvelope) -> dict:
    """The single entry point app.routers.whatsapp_bridge calls for every
    inbound message the bridge forwards. Every early return below both
    replies to the user (when appropriate) and records a
    WhatsAppInboundMessage row -- see this module's own docstring for why
    every check here is re-derived from scratch, never trusted from a
    cached identity alone."""
    if queries.is_message_already_processed(db, envelope.provider, envelope.message_id):
        return {"status": "duplicate"}

    normalized_phone = normalize_phone_number(envelope.phone_number)

    try:
        enforce_rate_limit(
            [
                RateLimitCheck(
                    scope="whatsapp:inbound:phone",
                    identity=f"phone:{normalized_phone}",
                    rules=WHATSAPP_INBOUND_MESSAGE_RULES,
                )
            ]
        )
    except HTTPException:
        _record(
            db,
            message_id=envelope.message_id,
            organization_id=None,
            user_id=None,
            whatsapp_identity_id=None,
            message_type=envelope.type,
            command_action=None,
            status="rate_limited",
        )
        db.commit()
        return {"status": "rate_limited"}

    identity = queries.get_verified_identity_by_phone(db, envelope.provider, normalized_phone)

    if identity is None:
        handled = _try_handle_verification_code(db, normalized_phone, envelope)
        if not handled:
            _reply(normalized_phone, t("en", "whatsapp_not_linked"))
        _record(
            db,
            message_id=envelope.message_id,
            organization_id=None,
            user_id=None,
            whatsapp_identity_id=None,
            message_type=envelope.type,
            command_action="link_verify" if handled else None,
            status="processed" if handled else "rejected_unlinked",
        )
        db.commit()
        return {"status": "processed"}

    organization = db.get(Organization, identity.organization_id)
    language = get_language(organization)

    if not queries.is_user_active_member(db, identity.organization_id, identity.user_id):
        _reply(normalized_phone, t(language, "whatsapp_access_revoked"))
        _record(
            db,
            message_id=envelope.message_id,
            organization_id=identity.organization_id,
            user_id=identity.user_id,
            whatsapp_identity_id=identity.id,
            message_type=envelope.type,
            command_action=None,
            status="rejected_inactive",
        )
        db.commit()
        return {"status": "processed"}

    current_user = db.get(User, identity.user_id)
    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == identity.organization_id,
            OrganizationMember.user_id == identity.user_id,
        )
    )
    caller_role = MembershipRole(membership.role)
    queries.touch_identity_last_message(db, identity)

    def record(command_action: str | None, status: str, failure_code: str | None = None) -> None:
        _record(
            db,
            message_id=envelope.message_id,
            organization_id=identity.organization_id,
            user_id=identity.user_id,
            whatsapp_identity_id=identity.id,
            message_type=envelope.type,
            command_action=command_action,
            status=status,
            failure_code=failure_code,
        )

    try:
        require_whatsapp(db, identity.organization_id)
    except CapabilityDeniedError:
        _reply(normalized_phone, t(language, "whatsapp_plan_restricted"))
        record(None, "plan_restricted")
        db.commit()
        return {"status": "processed"}

    # Resolve message text -- transcribe if audio.
    if envelope.type == "audio":
        try:
            require_whatsapp_voice_messages(db, identity.organization_id)
        except CapabilityDeniedError:
            _reply(normalized_phone, t(language, "whatsapp_voice_plan_restricted"))
            record(None, "plan_restricted")
            db.commit()
            return {"status": "processed"}

        text = _transcribe(envelope, normalized_phone, language, record)
        if text is None:
            db.commit()
            return {"status": "processed"}
        _reply(normalized_phone, f"{t(language, 'whatsapp_transcript_prefix')} \"{text}\"")
    else:
        text = envelope.text.strip()

    if not text:
        record(None, "empty_message")
        db.commit()
        return {"status": "processed"}

    try:
        check_limit(db, identity.organization_id, LimitedResource.whatsapp_actions)
    except PlanLimitExceededError:
        _reply(normalized_phone, t(language, "whatsapp_quota_exceeded"))
        record(None, "plan_limit_reached")
        db.commit()
        return {"status": "processed"}

    normalized_text = text.strip().lower()
    context_store = get_context_store()

    if normalized_text in _HELP_WORDS:
        _reply(normalized_phone, t(language, "whatsapp_help_message"))
        record("help", "processed")
        db.commit()
        return {"status": "processed"}

    if normalized_text in _FORGET_WORDS:
        context_store.forget(identity.organization_id, current_user.id)
        _reply(normalized_phone, t(language, "whatsapp_context_forgotten"))
        record("forget_context", "processed")
        db.commit()
        return {"status": "processed"}

    if normalized_text in _CONFIRM_WORDS:
        context = context_store.get(identity.organization_id, current_user.id)
        if not context.pending_proposal_id:
            _reply(normalized_phone, t(language, "whatsapp_no_pending_action"))
            record("confirm", "failed", "no_pending_action")
        else:
            proposal_id = context.pending_proposal_id
            context_store.set_pending_proposal(identity.organization_id, current_user.id, None)
            try:
                result = confirm_action(
                    db,
                    identity.organization_id,
                    current_user,
                    proposal_id,
                    extra_rate_limit_checks=[
                        RateLimitCheck(
                            scope="assistant:action_confirm:phone",
                            identity=f"phone:{normalized_phone}",
                            rules=ASSISTANT_ACTION_CONFIRM_RULES,
                        )
                    ],
                )
                _reply(normalized_phone, _format_confirm_summary(result.action, result.summary, language))
                record(result.action, "processed")
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                _reply(normalized_phone, _format_error_code(detail.get("code", ""), language))
                record("confirm", "failed", detail.get("code"))
        db.commit()
        return {"status": "processed"}

    if normalized_text in _CANCEL_WORDS:
        context = context_store.get(identity.organization_id, current_user.id)
        proposal_id = context.pending_proposal_id
        context_store.set_pending_proposal(identity.organization_id, current_user.id, None)
        if proposal_id:
            try:
                cancel_action(db, identity.organization_id, current_user, proposal_id)
            except HTTPException:
                pass  # cancel is best-effort/idempotent -- any failure here is harmless.
        _reply(normalized_phone, t(language, "whatsapp_action_cancelled"))
        record("cancel", "processed")
        db.commit()
        return {"status": "processed"}

    doc_match = _match_document_request(text)
    if doc_match is not None:
        kind, reference = doc_match
        reply_text = _handle_document_send(db, identity, caller_role, kind, reference, normalized_phone, language)
        _reply(normalized_phone, reply_text)
        record(f"send_{kind}", "processed")
        db.commit()
        return {"status": "processed"}

    # Fall through to the AI assistant engine -- same tool registry, same
    # propose/confirm lifecycle the browser chat uses.
    try:
        require_ai(db, identity.organization_id)
        ai_provider = get_ai_provider()
    except (CapabilityDeniedError, HTTPException):
        _reply(normalized_phone, t(language, "whatsapp_generic_error"))
        record("assistant_query", "plan_restricted")
        db.commit()
        return {"status": "processed"}

    try:
        enforce_rate_limit(
            [
                RateLimitCheck(
                    scope="whatsapp:assistant_chat:phone",
                    identity=f"phone:{normalized_phone}",
                    rules=WHATSAPP_ASSISTANT_CHAT_RULES,
                )
            ]
        )
    except HTTPException:
        _reply(normalized_phone, t(language, "whatsapp_generic_error"))
        record("assistant_query", "rate_limited")
        db.commit()
        return {"status": "processed"}

    context = context_store.get(identity.organization_id, current_user.id)
    business_context = build_business_context(db, identity.organization_id)
    system_prompt = f"{ASSISTANT_SYSTEM_PROMPT}\n\n=== BUSINESS CONTEXT ===\n{format_business_context_as_text(business_context)}"
    messages = [ChatMessage(role=m.role, content=m.content) for m in context.messages] + [
        ChatMessage(role="user", content=text)
    ]

    try:
        stream_iterator = ai_provider.stream_complete(
            system_prompt, messages, tools=tool_definitions(allowed=ROLE_PERMISSIONS[caller_role])
        )
    except (AIProviderError, AIProviderTimeoutError):
        _reply(normalized_phone, t(language, "whatsapp_generic_error"))
        record("assistant_query", "failed", "ai_provider_error")
        db.commit()
        return {"status": "processed"}

    propose_checks = [
        RateLimitCheck(
            scope="whatsapp:action_propose:phone",
            identity=f"phone:{normalized_phone}",
            rules=WHATSAPP_ASSISTANT_ACTION_PROPOSE_RULES,
        )
    ]
    org_hash = identity.organization_id[:12]
    user_hash = identity.user_id[:12]

    text_parts: list[str] = []
    action_reply: str | None = None
    action_name = "assistant_query"
    try:
        for turn_event in run_chat_turn(
            db, identity.organization_id, current_user, caller_role, stream_iterator, propose_checks, org_hash, user_hash
        ):
            if isinstance(turn_event, TextDeltaEvent):
                text_parts.append(turn_event.text)
            elif isinstance(turn_event, ActionProposalEvent):
                context_store.set_pending_proposal(identity.organization_id, current_user.id, turn_event.proposal_id)
                action_reply = _format_proposal(turn_event, language)
                action_name = turn_event.action
            elif isinstance(turn_event, ClarificationEvent):
                action_reply = _format_clarification(turn_event, language)
            elif isinstance(turn_event, ErrorEvent):
                action_reply = _format_error_code(turn_event.code, language)
    except (AIProviderError, AIProviderTimeoutError):
        _reply(normalized_phone, t(language, "whatsapp_generic_error"))
        record("assistant_query", "failed", "ai_provider_error")
        db.commit()
        return {"status": "processed"}

    final_text = "".join(text_parts).strip()
    context_store.append_turn(identity.organization_id, current_user.id, "user", text)
    if final_text:
        context_store.append_turn(identity.organization_id, current_user.id, "assistant", final_text)

    reply_message = "\n\n".join(part for part in [final_text, action_reply] if part) or t(
        language, "whatsapp_generic_error"
    )
    _reply(normalized_phone, reply_message)
    record(action_name, "processed")
    db.commit()
    return {"status": "processed"}


def _transcribe(envelope: WhatsAppInboundEnvelope, normalized_phone: str, language: str, record) -> str | None:
    import base64

    media = envelope.media
    if media is None:
        _reply(normalized_phone, t(language, "whatsapp_audio_invalid_format"))
        record(None, "failed", "invalid_media")
        return None

    if media.mime_type.lower() not in WHATSAPP_ALLOWED_AUDIO_MIME_TYPES:
        _reply(normalized_phone, t(language, "whatsapp_audio_invalid_format"))
        record(None, "failed", "invalid_media_type")
        return None

    if media.size_bytes > WHATSAPP_AUDIO_MAX_BYTES:
        _reply(normalized_phone, t(language, "whatsapp_audio_too_large"))
        record(None, "failed", "audio_too_large")
        return None

    try:
        audio_bytes = base64.b64decode(media.content_base64)
    except (ValueError, TypeError):
        _reply(normalized_phone, t(language, "whatsapp_audio_invalid_format"))
        record(None, "failed", "invalid_media")
        return None

    if len(audio_bytes) > WHATSAPP_AUDIO_MAX_BYTES:
        _reply(normalized_phone, t(language, "whatsapp_audio_too_large"))
        record(None, "failed", "audio_too_large")
        return None

    try:
        transcript = get_transcription_provider().transcribe(audio_bytes, media.mime_type)
    except TranscriptionNotConfiguredError:
        _reply(normalized_phone, t(language, "whatsapp_transcription_unavailable"))
        record(None, "failed", "transcription_not_configured")
        return None
    except TranscriptionError:
        _reply(normalized_phone, t(language, "whatsapp_generic_error"))
        record(None, "failed", "transcription_failed")
        return None
    finally:
        # Never retained -- this is the only reference to the raw audio
        # bytes anywhere in this process; letting it go out of scope here
        # is the "temporary storage only, delete immediately" requirement
        # in its simplest possible form (no file ever touched disk).
        del audio_bytes

    return transcript.strip()


_CONFIRM_CANCEL_HINT = {
    "en": "Reply CONFIRM to continue or CANCEL to stop this action.",
    "es": "Respondé CONFIRMAR para continuar o CANCELAR para detener esta acción.",
}
_CLARIFICATION_PROMPT = {
    "en": "I found more than one match. Which one did you mean?",
    "es": "Encontré más de una coincidencia. ¿A cuál te referís?",
}


def _format_proposal(event: ActionProposalEvent, language: str) -> str:
    lines = [f"*{event.action}*"]
    for key, value in event.summary.items():
        lines.append(f"{key}: {value}")
    lines.append("")
    lines.append(_CONFIRM_CANCEL_HINT.get(language, _CONFIRM_CANCEL_HINT["en"]))
    return "\n".join(lines)


def _format_clarification(event: ClarificationEvent, language: str) -> str:
    prompt = _CLARIFICATION_PROMPT.get(language, _CLARIFICATION_PROMPT["en"])
    candidates = "\n".join(f"- {name}" for name in event.candidates)
    return f"{prompt}\n{candidates}"


def _format_confirm_summary(action: str, summary: dict, language: str) -> str:
    lines = [f"✅ *{action}*"]
    for key, value in summary.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def get_status_snapshot(db: Session, organization_id: str):
    from app.billing.capabilities import get_organization_capabilities

    caps = get_organization_capabilities(db, organization_id)
    provider = get_whatsapp_provider()
    connection = provider.get_connection_status()
    return {
        "transport_enabled": is_whatsapp_transport_enabled(),
        "transport_configured": is_whatsapp_transport_configured(),
        "plan_allows_whatsapp": caps.entitlements.whatsapp_enabled,
        "plan_allows_voice_messages": caps.entitlements.voice_messages_enabled,
        "connection": connection,
        "whatsapp_users_used": caps.usage_whatsapp_users,
        "whatsapp_users_limit": caps.entitlements.max_whatsapp_users,
        "whatsapp_actions_used": caps.usage_whatsapp_actions,
        "whatsapp_actions_limit": caps.entitlements.monthly_whatsapp_actions,
    }
