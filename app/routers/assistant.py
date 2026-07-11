import hashlib
import logging
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.base import AIProviderError, AIProviderTimeoutError, ChatMessage
from app.ai.factory import get_ai_provider
from app.ai.prompts import ASSISTANT_SYSTEM_PROMPT
from app.assistant_context import build_business_context, format_business_context_as_text
from app.database import get_db
from app.deps import get_current_user, require_org_member, require_verified_email
from app.models import User
from app.rate_limit import (
    RateLimitCheck,
    RateLimitRule,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
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


@router.post("/chat")
def assistant_chat(
    organization_id: str,
    body: AssistantChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    # Cheapest / most fundamental checks first, in order: membership, email
    # verification (this calls a paid external API — see the adjustment
    # that added this requirement), then rate limiting, then configuration,
    # then the actual (comparatively expensive) DB work of building context.
    require_org_member(current_user, organization_id, db)
    require_verified_email(current_user)

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
        stream_iterator = ai_provider.stream_complete(system_prompt, messages)
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

    def generate() -> Iterator[bytes]:
        # Never logs prompts, business context, or conversation content --
        # only identity hashes, provider/model, duration, success/failure,
        # and token usage if the provider returned it.
        try:
            for chunk in stream_iterator:
                yield chunk.encode("utf-8")
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
            # streaming response can do at this point is append a plain
            # explanation to what's already been sent.
            logger.warning(
                "assistant_chat: timeout mid-stream org_hash=%s user_hash=%s duration=%.2fs",
                org_hash,
                user_hash,
                time.monotonic() - start,
            )
            yield f"\n\n{GENERIC_TIMEOUT_ERROR_MESSAGE}".encode("utf-8")
        except AIProviderError:
            logger.error(
                "assistant_chat: provider error mid-stream org_hash=%s user_hash=%s duration=%.2fs",
                org_hash,
                user_hash,
                time.monotonic() - start,
            )
            yield f"\n\n{GENERIC_PROVIDER_ERROR_MESSAGE}".encode("utf-8")

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")
