import hashlib
import json
import logging
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.base import AIProviderError, AIProviderTimeoutError, ChatMessage, TextDelta, ToolInvocation
from app.ai.factory import get_ai_provider
from app.ai.limits import ASSISTANT_ACTION_TTL_SECONDS
from app.ai.prompts import ASSISTANT_SYSTEM_PROMPT
from app.ai.tools.registry import TOOL_PERMISSIONS, TOOL_REGISTRY, tool_definitions
from app.ai.tools.types import ActionToolError, AmbiguousCustomerError, AmbiguousProductError
from app.assistant_action_status import AssistantActionStatus
from app.assistant_context import build_business_context, format_business_context_as_text
from app.database import get_db
from app.deps import get_current_user, require_permission, require_verified_email
from app.membership_role import MembershipRole
from app.models import AssistantAction, User
from app.permissions import ROLE_PERMISSIONS, Permission, check_permission
from app.rate_limit import (
    RATE_LIMIT_CODE,
    RateLimitCheck,
    RateLimitRule,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
from app.schemas import AssistantChatRequest
from app.services.plan_limits import LimitedResource, PlanLimitExceededError, check_limit

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

    def _handle_tool_invocation(event: ToolInvocation) -> Iterator[bytes]:
        """Turns a single ToolInvocation into either an action_proposal, a
        clarification_needed, or an error NDJSON event. Never executes
        anything -- only ever inserts a `proposed` AssistantAction row.
        Provider output (event.arguments) is treated as fully untrusted
        until the tool's own Pydantic input_schema validates it."""
        tool = TOOL_REGISTRY.get(event.name)
        if tool is None:
            logger.warning(
                "assistant_chat: model called unknown tool=%s org_hash=%s user_hash=%s",
                event.name,
                org_hash,
                user_hash,
            )
            yield _ndjson({"type": "error", "code": "assistant_action_invalid"})
            return

        # Re-checked here even though tool_definitions() already filtered
        # by role above -- that filtering is only UX (don't offer actions
        # the model can't use), never the actual security boundary. A
        # malformed or replayed client request could still name a tool
        # that was never offered, so this is the real enforcement point.
        required_permission = TOOL_PERMISSIONS.get(tool.name)
        if required_permission is not None and not check_permission(caller_role, required_permission):
            logger.warning(
                "assistant_chat: permission denied tool=%s role=%s org_hash=%s user_hash=%s",
                event.name,
                caller_role.value,
                org_hash,
                user_hash,
            )
            yield _ndjson({"type": "error", "code": "permission_denied"})
            return

        # Only ever consumed on this branch (an actual tool call), never
        # for plain-text turns -- see ASSISTANT_ACTION_PROPOSE_RULES.
        try:
            enforce_rate_limit(
                [
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
            )
        except HTTPException as exc:
            # enforce_rate_limit normally raises before any response has
            # been sent; here we're already mid-stream, so a 429 can't be
            # sent as a fresh HTTP status -- surface it as an error event
            # instead, using the same stable code.
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            yield _ndjson({"type": "error", "code": detail.get("code", RATE_LIMIT_CODE)})
            return

        try:
            proposal = tool.build_proposal(db, organization_id, current_user, event.arguments)
        except AmbiguousCustomerError as exc:
            yield _ndjson(
                {
                    "type": "clarification_needed",
                    "code": exc.code,
                    "candidates": exc.candidate_names,
                }
            )
            return
        except AmbiguousProductError as exc:
            yield _ndjson(
                {
                    "type": "clarification_needed",
                    "code": exc.code,
                    "candidates": exc.candidate_names,
                }
            )
            return
        except ActionToolError as exc:
            yield _ndjson({"type": "error", "code": exc.code})
            return
        except ValidationError:
            # The model's tool call didn't match the tool's own input
            # schema -- never executed, never persisted.
            logger.warning(
                "assistant_chat: invalid tool arguments for tool=%s org_hash=%s user_hash=%s",
                tool.name,
                org_hash,
                user_hash,
            )
            yield _ndjson({"type": "error", "code": "assistant_action_invalid"})
            return

        # Checked right before the insert, after the (possibly slow)
        # provider round-trip and build_proposal() have already
        # completed -- never held across the external AI call itself
        # (see app.services.plan_limits._lock_organization's own
        # docstring on why that lock's held duration matters). This is a
        # streaming NDJSON response, not an ordinary JSON endpoint, so a
        # 409 can't be raised as a fresh HTTP status here -- surfaced as
        # an error event instead, same as the rate-limit check above.
        try:
            check_limit(db, organization_id, LimitedResource.ai_actions)
        except PlanLimitExceededError as exc:
            yield _ndjson({"type": "error", **exc.to_error_detail()})
            return

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ASSISTANT_ACTION_TTL_SECONDS)
        action = AssistantAction(
            organization_id=organization_id,
            user_id=current_user.id,
            action_name=tool.name,
            input_payload=json.dumps(proposal.resolved_input),
            summary=json.dumps(proposal.summary),
            status=AssistantActionStatus.proposed.value,
            expires_at=expires_at,
        )
        db.add(action)
        db.commit()
        db.refresh(action)

        logger.info(
            "assistant_chat: proposal created action_id=%s action_name=%s "
            "org_hash=%s user_hash=%s",
            action.id,
            tool.name,
            org_hash,
            user_hash,
        )
        yield _ndjson(
            {
                "type": "action_proposal",
                "proposal_id": action.id,
                "action": tool.name,
                "summary": proposal.summary,
                "expires_at": expires_at.isoformat(),
            }
        )

    def generate() -> Iterator[bytes]:
        # Never logs prompts, business context, or conversation content --
        # only identity hashes, provider/model, duration, success/failure,
        # and token usage if the provider returned it.
        tool_call_handled = False
        try:
            for event in stream_iterator:
                if isinstance(event, TextDelta):
                    if event.text:
                        yield _ndjson({"type": "text_delta", "text": event.text})
                elif isinstance(event, ToolInvocation):
                    if tool_call_handled:
                        # At most one proposal per user turn -- a model
                        # that calls more than one tool in the same reply
                        # has any call after the first logged and dropped,
                        # never turned into a second proposal.
                        logger.warning(
                            "assistant_chat: dropping extra tool call=%s in same turn "
                            "org_hash=%s user_hash=%s",
                            event.name,
                            org_hash,
                            user_hash,
                        )
                        continue
                    tool_call_handled = True
                    yield from _handle_tool_invocation(event)

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
