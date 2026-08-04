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

This router is now a thin wrapper: the actual confirm/cancel logic lives
in app.services.assistant_actions (Phase 23), extracted so the WhatsApp
channel can reuse the exact same lifecycle instead of a second, drifting
copy. This file's own job is only to add the one thing that legitimately
differs for an HTTP caller -- an IP-scoped rate-limit bucket alongside the
shared user-scoped one.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.rate_limit import RateLimitCheck, user_ip_identity
from app.schemas import AssistantActionCancelResponse, AssistantActionConfirmResponse
from app.services.assistant_actions import ASSISTANT_ACTION_CONFIRM_RULES, cancel_action, confirm_action

router = APIRouter(
    prefix="/organizations/{organization_id}/assistant/actions", tags=["assistant"]
)


@router.post("/{proposal_id}/confirm", response_model=AssistantActionConfirmResponse)
def confirm_assistant_action(
    organization_id: str,
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssistantActionConfirmResponse:
    return confirm_action(
        db,
        organization_id,
        current_user,
        proposal_id,
        extra_rate_limit_checks=[
            RateLimitCheck(
                scope="assistant:action_confirm:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=ASSISTANT_ACTION_CONFIRM_RULES,
            )
        ],
    )


@router.post("/{proposal_id}/cancel", response_model=AssistantActionCancelResponse)
def cancel_assistant_action(
    organization_id: str,
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssistantActionCancelResponse:
    return cancel_action(db, organization_id, current_user, proposal_id)
