"""Writes WebhookAuditLog rows -- append-only, mirrors
app.services.organization_api_key_audit.record_api_key_action's exact
shape and "does not commit, caller shares the transaction" contract."""

import json

from sqlalchemy.orm import Session

from app.models import User, WebhookAuditLog
from app.webhook_audit_action import WebhookAuditAction


def record_webhook_action(
    db: Session,
    *,
    organization_id: str,
    action: WebhookAuditAction,
    endpoint_id: str | None = None,
    actor: User | None = None,
    client_ip: str | None = None,
    details: dict | None = None,
) -> WebhookAuditLog:
    """Does not commit -- the caller adds this to the same transaction as
    whatever it's describing."""
    entry = WebhookAuditLog(
        organization_id=organization_id,
        endpoint_id=endpoint_id,
        actor_user_id=actor.id if actor is not None else None,
        action=action.value,
        details=json.dumps(details) if details is not None else None,
        client_ip=client_ip,
    )
    db.add(entry)
    return entry
