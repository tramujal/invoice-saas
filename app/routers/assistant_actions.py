"""Phase 2 of the AI assistant's action workflow: confirm or cancel a
proposal already created by POST .../assistant/chat (see
app/routers/assistant.py).

The request body for both endpoints is empty -- the client sends only a
proposal_id via the URL. Every business detail (resolved customer_id,
line items, invoice_id, new_status, ...) was already validated and
persisted at propose time, so there is nothing for the browser (or the
model, which never sees these endpoints at all) to smuggle into an
execution. See app/models.py's AssistantAction docstring and the
project's assistant-action plan for the full security model.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.tools.invoices import SendInvoiceEmailTool
from app.ai.tools.registry import TOOL_PERMISSIONS, TOOL_REGISTRY
from app.ai.tools.types import ActionToolError
from app.assistant_action_status import AssistantActionStatus
from app.database import get_db
from app.deps import get_current_user, require_org_member, require_permission, require_verified_email
from app.membership_role import MembershipRole
from app.models import AssistantAction, User
from app.permissions import Permission, check_permission
from app.rate_limit import (
    SEND_INVOICE_EMAIL_RULES,
    RateLimitCheck,
    RateLimitRule,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
from app.schemas import AssistantActionCancelResponse, AssistantActionConfirmResponse
from app.services.plan_limits import PlanLimitExceededError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/organizations/{organization_id}/assistant/actions", tags=["assistant"]
)

ASSISTANT_ACTION_CONFIRM_RULES = (RateLimitRule(limit=20, window_seconds=3600),)

NOT_FOUND_MESSAGE = "This action can no longer be found."
EXPIRED_MESSAGE = "This action has expired. Please ask the assistant again."
ALREADY_USED_MESSAGE = "This action has already been used."
INVALID_MESSAGE = "This action is no longer valid."
EXECUTION_FAILED_MESSAGE = "This action could not be completed. Please try again."


def _detail(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True)
    # columns (Postgres returns aware ones) -- normalize before comparing,
    # same convention as app/assistant_context.py's _stale_customers.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _load_locked_action(
    db: Session, organization_id: str, current_user: User, proposal_id: str
) -> AssistantAction:
    """Fetches the proposal row with a row lock and validates ownership +
    expiry, but does NOT change status itself -- confirm/cancel each
    perform their own specific transition afterward, still inside the same
    lock, so two racing requests for the same proposal can never both
    succeed (the second sees the already-updated status once it acquires
    the lock).

    Wrong organization, wrong user, and truly-missing all collapse into
    the same not-found response -- never a distinct 403 -- so a
    leaked/guessed proposal_id can't be used to probe whether it exists
    for someone else.
    """
    action = db.execute(
        select(AssistantAction).where(AssistantAction.id == proposal_id).with_for_update()
    ).scalar_one_or_none()

    if (
        action is None
        or action.organization_id != organization_id
        or action.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_detail("assistant_action_not_found", NOT_FOUND_MESSAGE),
        )

    now = datetime.now(timezone.utc)
    if action.status == AssistantActionStatus.proposed.value and now > _aware(action.expires_at):
        action.status = AssistantActionStatus.expired.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("assistant_action_expired", EXPIRED_MESSAGE),
        )

    if action.status != AssistantActionStatus.proposed.value:
        code = (
            "assistant_action_expired"
            if action.status == AssistantActionStatus.expired.value
            else "assistant_action_already_used"
        )
        message = EXPIRED_MESSAGE if code == "assistant_action_expired" else ALREADY_USED_MESSAGE
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_detail(code, message))

    return action


@router.post("/{proposal_id}/confirm", response_model=AssistantActionConfirmResponse)
def confirm_assistant_action(
    organization_id: str,
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssistantActionConfirmResponse:
    membership = require_permission(current_user, organization_id, Permission.assistant_execute, db)
    # Every AI-driven write requires verified email, uniformly -- even for
    # update_invoice_status, which the direct PATCH endpoint doesn't gate.
    # Deliberately stricter for this AI-driven surface: an LLM can be
    # coaxed into calling a tool far more easily than a human clicking a
    # status dropdown, so every confirmed action gets the same gate create
    # invoice / send email already have.
    require_verified_email(current_user)

    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="assistant:action_confirm:user",
                identity=user_identity(current_user.id),
                rules=ASSISTANT_ACTION_CONFIRM_RULES,
            ),
            RateLimitCheck(
                scope="assistant:action_confirm:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=ASSISTANT_ACTION_CONFIRM_RULES,
            ),
        ]
    )

    action = _load_locked_action(db, organization_id, current_user, proposal_id)

    tool = TOOL_REGISTRY.get(action.action_name)
    if tool is None:
        # Should never happen -- action_name is only ever set from a
        # currently-registered tool at propose time -- but treat a
        # since-removed tool the same as an invalid proposal rather than
        # letting a KeyError/AttributeError leak.
        action.status = AssistantActionStatus.failed.value
        action.failure_code = "assistant_action_invalid"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail("assistant_action_invalid", INVALID_MESSAGE),
        )

    # Re-checked here, not just trusted from propose time -- the caller's
    # role could have changed between propose and confirm (e.g. a
    # demotion mid-session). This uses the exact same check_permission/
    # TOOL_PERMISSIONS the propose endpoint (app/routers/assistant.py)
    # does -- there is no separate AI-specific authorization
    # implementation anywhere, so the AI Agent can never bypass it.
    required_permission = TOOL_PERMISSIONS.get(tool.name)
    if required_permission is not None and not check_permission(
        MembershipRole(membership.role), required_permission
    ):
        action.status = AssistantActionStatus.failed.value
        action.failure_code = "permission_denied"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_detail("permission_denied", "You no longer have permission to perform this action."),
        )

    try:
        resolved = tool.resolved_schema.model_validate_json(action.input_payload)
    except ValidationError:
        # Defense in depth against schema drift between propose and
        # confirm (e.g. a deploy landed mid-session) -- never execute a
        # payload that doesn't match the tool's current resolved schema.
        action.status = AssistantActionStatus.failed.value
        action.failure_code = "assistant_action_invalid"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail("assistant_action_invalid", INVALID_MESSAGE),
        )

    # send_invoice_email shares the exact same rate-limit bucket
    # (identical scope strings) as the direct POST
    # .../invoices/{id}/send-email endpoint -- an AI-confirmed send must
    # never get a separate, fresh budget from the one a human clicking
    # "send" already shares.
    if tool.name == SendInvoiceEmailTool.name:
        enforce_rate_limit(
            [
                RateLimitCheck(
                    scope="invoices:send_email:user",
                    identity=user_identity(current_user.id),
                    rules=SEND_INVOICE_EMAIL_RULES,
                ),
                RateLimitCheck(
                    scope="invoices:send_email:user_ip",
                    identity=user_ip_identity(request, current_user.id),
                    rules=SEND_INVOICE_EMAIL_RULES,
                ),
            ]
        )

    try:
        result = tool.execute(db, organization_id, current_user, resolved)
    except ActionToolError:
        action.status = AssistantActionStatus.failed.value
        action.failure_code = "assistant_action_execution_failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_detail("assistant_action_execution_failed", EXECUTION_FAILED_MESSAGE),
        )
    except PlanLimitExceededError as exc:
        # The same centralized check every direct-create endpoint goes
        # through (see app.services.plan_limits) -- an AI-confirmed
        # invoice/quote creation is never a backdoor around the
        # organization's plan limit. Surfaced with the same structured
        # 409 body as everywhere else, not the generic execution-failed
        # shape, so the frontend's one shared dialog handles this too.
        action.status = AssistantActionStatus.failed.value
        action.failure_code = "plan_limit_reached"
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())

    action.status = AssistantActionStatus.executed.value
    action.executed_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(
        "confirm_assistant_action: executed action_id=%s action_name=%s",
        action.id,
        tool.name,
    )
    return AssistantActionConfirmResponse(status="executed", action=tool.name, summary=result.summary)


@router.post("/{proposal_id}/cancel", response_model=AssistantActionCancelResponse)
def cancel_assistant_action(
    organization_id: str,
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssistantActionCancelResponse:
    require_org_member(current_user, organization_id, db)

    action = db.execute(
        select(AssistantAction).where(AssistantAction.id == proposal_id).with_for_update()
    ).scalar_one_or_none()

    if (
        action is None
        or action.organization_id != organization_id
        or action.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_detail("assistant_action_not_found", NOT_FOUND_MESSAGE),
        )

    # Cancelling an already-cancelled proposal is idempotent -- a
    # double-click on "Cancel" should never surface an error.
    if action.status == AssistantActionStatus.cancelled.value:
        return AssistantActionCancelResponse(status="cancelled")

    now = datetime.now(timezone.utc)
    if action.status == AssistantActionStatus.proposed.value and now > _aware(action.expires_at):
        action.status = AssistantActionStatus.expired.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("assistant_action_expired", EXPIRED_MESSAGE),
        )

    if action.status != AssistantActionStatus.proposed.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("assistant_action_already_used", ALREADY_USED_MESSAGE),
        )

    action.status = AssistantActionStatus.cancelled.value
    db.commit()
    return AssistantActionCancelResponse(status="cancelled")
