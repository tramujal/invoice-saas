"""Confirm/cancel logic for an AssistantAction proposal -- extracted from
app.routers.assistant_actions (which used to inline all of this) so a
second caller -- app.whatsapp.service (Phase 23) -- can reuse the exact
same propose->confirm->cancel lifecycle instead of a second, drifting
copy. Mirrors app.services.customers's own extraction rationale exactly:
same behavior, same HTTPException shapes, just callable from anywhere.

Every check here is IDENTICAL regardless of caller: permission re-check
against the membership fetched fresh in this call (never trusted from
propose time), verified-email gate, tool-specific rate-limit reuse
(send_invoice_email shares its bucket with the direct HTTP endpoint),
resolved-schema re-validation, and PlanLimitExceededError handling. The
one thing that legitimately differs per channel is rate-limit identity
(a browser request has an IP; a WhatsApp message has a phone number
instead) -- callers build their own extra RateLimitCheck list and pass it
in; nothing else about this module is channel-aware.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.tools.invoices import SendInvoiceEmailTool
from app.ai.tools.registry import TOOL_PERMISSIONS, TOOL_REGISTRY
from app.ai.tools.types import ActionToolError
from app.assistant_action_status import AssistantActionStatus
from app.deps import require_org_member, require_permission, require_verified_email
from app.membership_role import MembershipRole
from app.models import AssistantAction, User
from app.permissions import Permission, check_permission
from app.rate_limit import (
    SEND_INVOICE_EMAIL_RULES,
    RateLimitCheck,
    RateLimitRule,
    enforce_rate_limit,
    user_identity,
)
from app.schemas import AssistantActionCancelResponse, AssistantActionConfirmResponse
from app.services.plan_limits import PlanLimitExceededError

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
    # columns (Postgres returns aware ones) -- normalize before comparing.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _load_locked_action(
    db: Session, organization_id: str, current_user: User, proposal_id: str
) -> AssistantAction:
    """Fetches the proposal row with a row lock and validates ownership +
    expiry, but does NOT change status itself -- confirm/cancel each
    perform their own specific transition afterward, still inside the
    same lock, so two racing requests for the same proposal (from the
    same channel or different ones) can never both succeed.

    Wrong organization, wrong user, and truly-missing all collapse into
    the same not-found response -- never a distinct 403 -- so a
    leaked/guessed proposal_id can't be used to probe whether it exists
    for someone else."""
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


def confirm_action(
    db: Session,
    organization_id: str,
    current_user: User,
    proposal_id: str,
    *,
    extra_rate_limit_checks: list[RateLimitCheck] = (),
) -> AssistantActionConfirmResponse:
    """Confirms a `proposed` AssistantAction, executing its tool. Raises
    HTTPException with the exact same status/detail shape the HTTP router
    always returned -- callers that aren't FastAPI request handlers (the
    WhatsApp channel) still get a structured `.status_code`/`.detail` to
    translate into a channel-appropriate message; they just don't get a
    literal HTTP response out of it.

    `extra_rate_limit_checks` lets each channel add its own identity-scoped
    bucket (IP for the browser, phone for WhatsApp) on top of the shared
    user-only one -- see this module's own docstring."""
    membership = require_permission(current_user, organization_id, Permission.assistant_execute, db)
    # Every AI-driven write requires verified email, uniformly -- even for
    # update_invoice_status, which the direct PATCH endpoint doesn't gate.
    require_verified_email(current_user)

    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="assistant:action_confirm:user",
                identity=user_identity(current_user.id),
                rules=ASSISTANT_ACTION_CONFIRM_RULES,
            ),
            *extra_rate_limit_checks,
        ]
    )

    action = _load_locked_action(db, organization_id, current_user, proposal_id)

    tool = TOOL_REGISTRY.get(action.action_name)
    if tool is None:
        # Should never happen -- action_name is only ever set from a
        # currently-registered tool at propose time.
        action.status = AssistantActionStatus.failed.value
        action.failure_code = "assistant_action_invalid"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail("assistant_action_invalid", INVALID_MESSAGE),
        )

    # Re-checked here, not just trusted from propose time -- the caller's
    # role could have changed between propose and confirm. Same
    # check_permission/TOOL_PERMISSIONS every channel uses -- no separate
    # AI- or channel-specific authorization implementation anywhere.
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
        action.status = AssistantActionStatus.failed.value
        action.failure_code = "assistant_action_invalid"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_detail("assistant_action_invalid", INVALID_MESSAGE),
        )

    # send_invoice_email shares the exact same rate-limit bucket (identical
    # scope strings) as the direct POST .../invoices/{id}/send-email
    # endpoint -- a confirmed send must never get a separate, fresh budget
    # from the one a human clicking "send" already shares, regardless of
    # which channel confirmed it.
    if tool.name == SendInvoiceEmailTool.name:
        enforce_rate_limit(
            [
                RateLimitCheck(
                    scope="invoices:send_email:user",
                    identity=user_identity(current_user.id),
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
        action.status = AssistantActionStatus.failed.value
        action.failure_code = "plan_limit_reached"
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_error_detail())

    action.status = AssistantActionStatus.executed.value
    action.executed_at = datetime.now(timezone.utc)
    db.commit()

    return AssistantActionConfirmResponse(status="executed", action=tool.name, summary=result.summary)


def cancel_action(
    db: Session,
    organization_id: str,
    current_user: User,
    proposal_id: str,
) -> AssistantActionCancelResponse:
    """Cancels a `proposed` AssistantAction. Only require_org_member (not
    assistant_execute) -- cancelling is not a privileged action, same as
    before. Idempotent on repeat cancel."""
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
