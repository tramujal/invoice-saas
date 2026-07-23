"""Writes PlatformAuditLog rows -- append-only, one row per successful
platform-administration mutation. Never called on a failed/rejected
attempt (permission denial, validation error, conflict): callers only
reach this after every other check has already passed, so a row here
always corresponds to a real state change that actually happened.
"""

import json

from sqlalchemy.orm import Session

from app.models import Organization, PlatformAuditLog, User
from app.platform_audit_action import PlatformAuditAction


def record_organization_action(
    db: Session,
    *,
    actor: User,
    action: PlatformAuditAction,
    organization: Organization,
    reason: str,
    client_ip: str | None,
) -> PlatformAuditLog:
    """Does not commit -- the caller adds this to the same transaction as
    the actual status change, so the audit row and the mutation it
    describes either both persist or neither does."""
    entry = PlatformAuditLog(
        actor_user_id=actor.id,
        actor_email=actor.email,
        action=action.value,
        target_organization_id=organization.id,
        target_organization_name=organization.business_name or organization.name,
        reason=reason,
        client_ip=client_ip,
    )
    db.add(entry)
    return entry


def record_user_action(
    db: Session,
    *,
    actor: User,
    action: PlatformAuditAction,
    target_user: User,
    reason: str,
    client_ip: str | None,
    details: dict | None = None,
) -> PlatformAuditLog:
    """Sibling of record_organization_action for actions that target a
    USER rather than an organization -- target_organization_id/name are
    left at their defaults (NULL/"", meaning "not applicable," same
    convention as Customer.tax_id) rather than reusing them for a user's
    id/email. `details` (e.g. {"old_role": ..., "new_role": ...} for a
    platform-role change) is JSON-encoded into a plain TEXT column so it
    works identically on SQLite and Postgres. Does not commit -- follows
    record_organization_action's same-transaction contract."""
    entry = PlatformAuditLog(
        actor_user_id=actor.id,
        actor_email=actor.email,
        action=action.value,
        target_user_id=target_user.id,
        target_user_email=target_user.email,
        reason=reason,
        details=json.dumps(details) if details is not None else None,
        client_ip=client_ip,
    )
    db.add(entry)
    return entry


def record_settings_action(
    db: Session,
    *,
    actor: User,
    reason: str,
    client_ip: str | None,
    details: dict | None = None,
) -> PlatformAuditLog:
    """Sibling of record_organization_action/record_user_action for the
    one platform-level action that has no target at all (platform.
    settings_updated) -- both target_organization_id/target_user_id stay
    None, and target_organization_name stays at its "" default, exactly
    matching PlatformAuditLog's own documented "not applicable"
    convention. `details` carries the changed-field diff (see
    app.routers.platform_admin's PATCH /admin/settings handler for the
    {"field": {"old": ..., "new": ...}} shape) -- never a secret, since
    every field on PlatformSettings is itself a non-secret dynamic
    setting by construction (see that model's own docstring)."""
    entry = PlatformAuditLog(
        actor_user_id=actor.id,
        actor_email=actor.email,
        action=PlatformAuditAction.platform_settings_updated.value,
        reason=reason,
        details=json.dumps(details) if details is not None else None,
        client_ip=client_ip,
    )
    db.add(entry)
    return entry
