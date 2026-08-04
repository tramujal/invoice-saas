import hashlib
import json
import logging
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.base import AIProviderError, AIProviderTimeoutError, ChatMessage
from app.ai.engine import ActionProposalEvent, ClarificationEvent, ErrorEvent, TextDeltaEvent, run_chat_turn
from app.ai.factory import get_ai_provider
from app.ai.prompts import ASSISTANT_SYSTEM_PROMPT
from app.ai.tools.registry import tool_definitions
from app.assistant_context import build_business_context, format_business_context_as_text
from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.membership_role import MembershipRole
from app.models import User
from app.permissions import ROLE_PERMISSIONS, Permission
from app.rate_limit import (
    RateLimitCheck,
    RateLimitRule,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
from app.billing.enforcement import CapabilityDeniedError, require_ai
from app.schemas import AssistantChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/organizations/{organization_id}/assistant", tags=["assistant"]
)

# Calls a paid external API, so it gets the same two-bucket treatment as
# the other authenticated, cost-sensitive actions (resend-verification,
# send-invoice-email): a user-only bucket that can't be evaded by
# switching IPs, and a user+IP bucket for single-source abuse.
ASSISTANT_CHAT_RULES = (RateLimitRule(limit=20, window_seconds=3600),)

# Tighter than plain chat and only ever consumed on the branch where the
# model actually calls a tool (see _handle_tool_invocation) -- proposing a
# business action is more consequential than an ordinary Q&A turn, so it
# gets its own, smaller budget rather than sharing ASSISTANT_CHAT_RULES.
ASSISTANT_ACTION_PROPOSE_RULES = (RateLimitRule(limit=10, window_seconds=3600),)

GENERIC_PROVIDER_ERROR_MESSAGE = (
    "The assistant is temporarily unavailable. Please try again later."
)
GENERIC_TIMEOUT_ERROR_MESSAGE = (
    "The assistant took too long to respond. Please try again."
)


def _hash_for_log(value: str) -> str:
    """Never logs a raw organization/user id — only a short, stable,
    non-reversible fingerprint, matching app.rate_limit's own logging
    convention."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _ndjson(payload: dict) -> bytes:
    """Serializes one NDJSON event line. Every event the client can ever
    receive is one of: text_delta, action_proposal, clarification_needed,
    error -- see the frontend's assistant page for the matching parser."""
    return (json.dumps(payload) + "\n").encode("utf-8")


@router.post("/chat")
def assistant_chat(
    organization_id: str,
    body: AssistantChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    # Cheapest / most fundamental checks first, in order: membership+
    # permission, email verification (this calls a paid external API — see
    # the adjustment that added this requirement), then rate limiting, then
    # configuration, then the actual (comparatively expensive) DB work of
    # building context.
    membership = require_permission(current_user, organization_id, Permission.assistant_chat, db)
    require_verified_email(current_user)
    caller_role = MembershipRole(membership.role)

    # Phase 17B: the all-or-nothing AI feature flag, checked before rate
    # limiting and before the (paid, comparatively expensive) provider
    # call below -- a plan without AI at all should never reach either.
    # The per-month ai_actions quota (LimitedResource.ai_actions) still
    # applies on top of this, later, only once a tool is actually
    # proposed -- see _handle_tool_invocation.
    try:
        require_ai(db, organization_id)
    except CapabilityDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_error_detail())

    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="assistant:chat:user",
                identity=user_identity(current_user.id),
                rules=ASSISTANT_CHAT_RULES,
            ),
            RateLimitCheck(
                scope="assistant:chat:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=ASSISTANT_CHAT_RULES,
            ),
        ]
    )

    # get_ai_provider() is called explicitly here (not as a FastAPI Depends
    # parameter) so it only runs after the checks above -- exactly like
    # get_email_sender() in send_invoice_email. A Depends parameter would
    # resolve before require_org_member/require_verified_email/rate
    # limiting ever ran, which would let an unconfigured-AI 503 leak before
    # authorization even happened.
    ai_provider = get_ai_provider()

    context = build_business_context(db, organization_id)
    context_text = format_business_context_as_text(context)
    system_prompt = f"{ASSISTANT_SYSTEM_PROMPT}\n\n=== BUSINESS CONTEXT ===\n{context_text}"

    # body.history has already been validated/bounded by AssistantChatRequest
    # (role restricted to user/assistant, per-message and list-length caps,
    # total-size cap) -- only empty messages are still filtered here, since
    # that was a deliberate "trim rather than reject" case.
    history = [
        ChatMessage(role=m.role, content=m.content)
        for m in body.history
        if m.content.strip()
    ]
    messages = history + [ChatMessage(role="user", content=body.message)]

    org_hash = _hash_for_log(organization_id)
    user_hash = _hash_for_log(current_user.id)

    # The provider's initial request (auth, model validation, connection)
    # happens here, synchronously -- see AIProvider.stream_complete's
    # contract -- so a failure at this stage still gets a clean HTTP status
    # (502/504) instead of being silently downgraded to in-stream text,
    # which is the best this can do once a 200 has actually been sent.
    start = time.monotonic()
    try:
        stream_iterator = ai_provider.stream_complete(
            system_prompt, messages, tools=tool_definitions(allowed=ROLE_PERMISSIONS[caller_role])
        )
    except AIProviderTimeoutError:
        logger.warning(
            "assistant_chat: provider timed out before streaming began "
            "org_hash=%s user_hash=%s duration=%.2fs",
            org_hash,
            user_hash,
            time.monotonic() - start,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "ai_timeout", "message": GENERIC_TIMEOUT_ERROR_MESSAGE},
        )
    except AIProviderError:
        logger.error(
            "assistant_chat: provider failed before streaming began "
            "org_hash=%s user_hash=%s duration=%.2fs",
            org_hash,
            user_hash,
            time.monotonic() - start,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ai_provider_error", "message": GENERIC_PROVIDER_ERROR_MESSAGE},
        )

    def _turn_event_to_ndjson(turn_event) -> bytes:
        """Translates a channel-agnostic app.ai.engine.TurnEvent into this
        endpoint's NDJSON wire format -- the only thing that changed when
        the tool-call loop moved to app.ai.engine (Phase 23, for the
        WhatsApp channel to reuse): this function, not the loop itself."""
        if isinstance(turn_event, TextDeltaEvent):
            return _ndjson({"type": "text_delta", "text": turn_event.text})
        if isinstance(turn_event, ActionProposalEvent):
            return _ndjson(
                {
                    "type": "action_proposal",
                    "proposal_id": turn_event.proposal_id,
                    "action": turn_event.action,
                    "summary": turn_event.summary,
                    "expires_at": turn_event.expires_at,
                }
            )
        if isinstance(turn_event, ClarificationEvent):
            return _ndjson(
                {"type": "clarification_needed", "code": turn_event.code, "candidates": turn_event.candidates}
            )
        # ErrorEvent
        return _ndjson({"type": "error", "code": turn_event.code})

    # Only ever consumed on the branch where the model actually calls a
    # tool (see app.ai.engine._handle_tool_invocation), never for plain-
    # text turns -- see ASSISTANT_ACTION_PROPOSE_RULES.
    propose_rate_limit_checks = [
        RateLimitCheck(
            scope="assistant:action_propose:user",
            identity=user_identity(current_user.id),
            rules=ASSISTANT_ACTION_PROPOSE_RULES,
        ),
        RateLimitCheck(
            scope="assistant:action_propose:user_ip",
            identity=user_ip_identity(request, current_user.id),
            rules=ASSISTANT_ACTION_PROPOSE_RULES,
        ),
    ]

    def generate() -> Iterator[bytes]:
        # Never logs prompts, business context, or conversation content --
        # only identity hashes, provider/model, duration, success/failure,
        # and token usage if the provider returned it.
        try:
            for turn_event in run_chat_turn(
                db,
                organization_id,
                current_user,
                caller_role,
                stream_iterator,
                propose_rate_limit_checks,
                org_hash,
                user_hash,
            ):
                yield _turn_event_to_ndjson(turn_event)

            duration = time.monotonic() - start
            usage = getattr(ai_provider, "last_usage", None)
            logger.info(
                "assistant_chat: success org_hash=%s user_hash=%s provider=%s model=%s "
                "duration=%.2fs usage=%s",
                org_hash,
                user_hash,
                ai_provider.__class__.__name__,
                getattr(ai_provider, "model", "?"),
                duration,
                usage,
            )
        except AIProviderTimeoutError:
            # Can only happen once streaming has already started (the
            # eager check above catches the common case); the best a
            # streaming response can do at this point is append an error
            # event to what's already been sent.
            logger.warning(
                "assistant_chat: timeout mid-stream org_hash=%s user_hash=%s duration=%.2fs",
                org_hash,
                user_hash,
                time.monotonic() - start,
            )
            yield _ndjson({"type": "error", "code": "ai_timeout"})
        except AIProviderError:
            logger.error(
                "assistant_chat: provider error mid-stream org_hash=%s user_hash=%s duration=%.2fs",
                org_hash,
                user_hash,
                time.monotonic() - start,
            )
            yield _ndjson({"type": "error", "code": "ai_provider_error"})

    return StreamingResponse(generate(), media_type="application/x-ndjson")
