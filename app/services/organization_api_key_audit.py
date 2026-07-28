"""Writes OrganizationApiKeyAuditLog rows -- append-only, covering both
API-key lifecycle events (created/rotated/revoked, always with a real
actor) and authentication-time events (auth failed, revoked/expired key
used, permission denied -- often with NO actor, since a rejected
request was never authenticated as anyone).

Mirrors app.services.platform_audit's own shape and "does not commit,
caller shares the transaction" contract, adapted for a nullable actor.
"""

import json

from sqlalchemy.orm import Session

from app.api_key_audit_action import ApiKeyAuditAction
from app.models import OrganizationApiKeyAuditLog, User


def record_api_key_action(
    db: Session,
    *,
    organization_id: str,
    action: ApiKeyAuditAction,
    api_key_id: str | None = None,
    actor: User | None = None,
    client_ip: str | None = None,
    details: dict | None = None,
) -> OrganizationApiKeyAuditLog:
    """Does not commit -- the caller adds this to the same transaction as
    whatever it's describing (a lifecycle event) or commits it alone
    right after an auth-time rejection (there is no other mutation to
    share a transaction with in that case)."""
    entry = OrganizationApiKeyAuditLog(
        organization_id=organization_id,
        api_key_id=api_key_id,
        actor_user_id=actor.id if actor is not None else None,
        action=action.value,
        details=json.dumps(details) if details is not None else None,
        client_ip=client_ip,
    )
    db.add(entry)
    return entry
