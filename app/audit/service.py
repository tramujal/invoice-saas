"""record_audit_entry -- the only function that writes an AuditEntry row.

Called exactly once, from inside app.notifications.service.emit_event's
own fan-out (the audit subsystem's designated position as "just another
consumer of emit_event," per Phase 22's governance requirement) -- never
from a router, a service function, or anywhere else. Like
record_webhook_event, this never commits: the caller's own existing
db.commit() (already present at the business-mutation call site) is what
makes this row durable, in the same transaction as the mutation that
caused it and every other emit_event channel.
"""

import json

from sqlalchemy.orm import Session

from app.models import AuditEntry
from app.webhook_event_type import WebhookEventType


def record_audit_entry(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str | None,
    event_type: WebhookEventType,
    object_type: str,
    object_id: str,
    payload: dict,
) -> AuditEntry:
    entry = AuditEntry(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type=event_type.value,
        resource_type=object_type,
        resource_id=object_id,
        metadata_json=json.dumps(payload, default=str),
    )
    db.add(entry)
    db.flush()
    return entry
