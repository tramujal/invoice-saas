"""Transport-agnostic core of one assistant "turn" -- extracted from
app.routers.assistant so a second caller (app.whatsapp.service, Phase 23)
can reuse the exact same tool-call/propose loop instead of a second,
drifting copy. app.routers.assistant's own `generate()` is now a thin
wrapper around run_chat_turn() below that turns each TurnEvent into an
NDJSON line; nothing about its behavior, checks, or ordering changed.

This module deliberately knows nothing about HTTP, NDJSON, or WhatsApp --
it consumes an already-opened AIProvider stream and yields plain,
serialization-agnostic TurnEvent values. Every check this module performs
(tool permission re-check, propose-tier rate limit, plan quota) is
IDENTICAL for every caller -- there is exactly one place a tool call turns
into an AssistantAction row, regardless of which channel proposed it.
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.base import StreamEvent, TextDelta, ToolInvocation
from app.ai.limits import ASSISTANT_ACTION_TTL_SECONDS
from app.ai.tools.registry import TOOL_PERMISSIONS, TOOL_REGISTRY
from app.ai.tools.types import ActionToolError, AmbiguousCustomerError, AmbiguousProductError
from app.assistant_action_status import AssistantActionStatus
from app.membership_role import MembershipRole
from app.models import AssistantAction, User
from app.permissions import Permission, check_permission
from app.rate_limit import RateLimitCheck, enforce_rate_limit
from app.services.plan_limits import LimitedResource, PlanLimitExceededError, check_limit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextDeltaEvent:
    text: str


@dataclass(frozen=True)
class ActionProposalEvent:
    proposal_id: str
    action: str
    summary: dict
    expires_at: str


@dataclass(frozen=True)
class ClarificationEvent:
    code: str
    candidates: list[str]


@dataclass(frozen=True)
class ErrorEvent:
    code: str


TurnEvent = TextDeltaEvent | ActionProposalEvent | ClarificationEvent | ErrorEvent


def _handle_tool_invocation(
    db: Session,
    organization_id: str,
    current_user: User,
    caller_role: MembershipRole,
    event: ToolInvocation,
    propose_rate_limit_checks: list[RateLimitCheck],
    org_hash: str,
    user_hash: str,
) -> Iterator[TurnEvent]:
    """Turns a single ToolInvocation into either an ActionProposalEvent, a
    ClarificationEvent, or an ErrorEvent. Never executes anything -- only
    ever inserts a `proposed` AssistantAction row. Provider output
    (event.arguments) is treated as fully untrusted until the tool's own
    Pydantic input_schema validates it. Identical logic regardless of
    which channel is calling this (HTTP chat, WhatsApp text/voice)."""
    tool = TOOL_REGISTRY.get(event.name)
    if tool is None:
        logger.warning(
            "assistant_engine: model called unknown tool=%s org_hash=%s user_hash=%s",
            event.name,
            org_hash,
            user_hash,
        )
        yield ErrorEvent(code="assistant_action_invalid")
        return

    # Re-checked here even though the caller already filtered available
    # tools by role -- that filtering is only UX (don't offer actions the
    # model can't use), never the actual security boundary. A malformed
    # or replayed call could still name a tool that was never offered, so
    # this is the real enforcement point -- the exact same check_permission
    # /TOOL_PERMISSIONS every HTTP router already uses, no separate
    # AI-specific or channel-specific authorization implementation.
    required_permission = TOOL_PERMISSIONS.get(tool.name)
    if required_permission is not None and not check_permission(caller_role, required_permission):
        logger.warning(
            "assistant_engine: permission denied tool=%s role=%s org_hash=%s user_hash=%s",
            event.name,
            caller_role.value,
            org_hash,
            user_hash,
        )
        yield ErrorEvent(code="permission_denied")
        return

    try:
        enforce_rate_limit(propose_rate_limit_checks)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        yield ErrorEvent(code=detail.get("code", "rate_limit_exceeded"))
        return

    try:
        proposal = tool.build_proposal(db, organization_id, current_user, event.arguments)
    except AmbiguousCustomerError as exc:
        yield ClarificationEvent(code=exc.code, candidates=exc.candidate_names)
        return
    except AmbiguousProductError as exc:
        yield ClarificationEvent(code=exc.code, candidates=exc.candidate_names)
        return
    except ActionToolError as exc:
        yield ErrorEvent(code=exc.code)
        return
    except ValidationError:
        logger.warning(
            "assistant_engine: invalid tool arguments for tool=%s org_hash=%s user_hash=%s",
            tool.name,
            org_hash,
            user_hash,
        )
        yield ErrorEvent(code="assistant_action_invalid")
        return

    try:
        check_limit(db, organization_id, LimitedResource.ai_actions)
    except PlanLimitExceededError as exc:
        yield ErrorEvent(code=exc.to_error_detail()["code"])
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
        "assistant_engine: proposal created action_id=%s action_name=%s org_hash=%s user_hash=%s",
        action.id,
        tool.name,
        org_hash,
        user_hash,
    )
    yield ActionProposalEvent(
        proposal_id=action.id,
        action=tool.name,
        summary=proposal.summary,
        expires_at=expires_at.isoformat(),
    )


def run_chat_turn(
    db: Session,
    organization_id: str,
    current_user: User,
    caller_role: MembershipRole,
    stream_iterator: Iterator[StreamEvent],
    propose_rate_limit_checks: list[RateLimitCheck],
    org_hash: str,
    user_hash: str,
) -> Iterator[TurnEvent]:
    """Consumes an already-opened AIProvider stream and yields TurnEvents:
    TextDeltaEvent for ordinary prose, and at most one of
    ActionProposalEvent/ClarificationEvent/ErrorEvent for a tool call (a
    model that calls more than one tool in the same reply has every call
    after the first logged and dropped -- at most one proposal per turn,
    regardless of channel).

    `propose_rate_limit_checks` is built by the caller since the identity
    differs per channel (user+IP for the HTTP chat endpoint, user+phone
    for WhatsApp) -- everything else here is identical no matter who's
    asking.
    """
    tool_call_handled = False
    for event in stream_iterator:
        if isinstance(event, TextDelta):
            if event.text:
                yield TextDeltaEvent(text=event.text)
        elif isinstance(event, ToolInvocation):
            if tool_call_handled:
                logger.warning(
                    "assistant_engine: dropping extra tool call=%s in same turn org_hash=%s user_hash=%s",
                    event.name,
                    org_hash,
                    user_hash,
                )
                continue
            tool_call_handled = True
            yield from _handle_tool_invocation(
                db,
                organization_id,
                current_user,
                caller_role,
                event,
                propose_rate_limit_checks,
                org_hash,
                user_hash,
            )
