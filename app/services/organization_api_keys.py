"""Organization API key lifecycle: create, list, lookup, revoke, rotate,
and the throttled last-used touch. The one place that constructs/mutates
OrganizationApiKey rows -- app.api_key_auth (authentication) and
app.routers.api_key_management (the browser-facing management endpoints)
both call into this module rather than touching the model directly, so
there is exactly one implementation of each lifecycle transition.

Audit-writing is embedded directly in create/revoke/rotate (rather than
left to each call site to remember, the way app.services.platform_audit
expects its routers to call it) -- this is a deliberate, narrow
deviation from that precedent: platform actions require an admin-
supplied `reason` string that only the router has, but API-key actions
need no such per-call context, so embedding the audit write here is
strictly safer (impossible to forget) with no loss of information.
"""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api_key_audit_action import ApiKeyAuditAction
from app.api_key_permissions import ApiKeyPermission
from app.api_keys import generate_api_key
from app.models import OrganizationApiKey, User
from app.services.organization_api_key_audit import record_api_key_action


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True)
    # columns (Postgres returns aware ones) -- normalize before comparing,
    # same convention as app.routers.assistant_actions's own _aware.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# How stale last_used_at/last_used_ip must be before a request bothers
# writing an update -- see touch_api_key_last_used's own docstring for
# why this throttling exists at all.
LAST_USED_TOUCH_INTERVAL = timedelta(minutes=5)


class ApiKeyNotFoundError(Exception):
    """No API key matches the given id within this organization."""


def create_api_key(
    db: Session,
    organization_id: str,
    actor: User,
    *,
    name: str,
    description: str,
    permissions: frozenset[ApiKeyPermission],
    expires_at: datetime | None,
    client_ip: str | None = None,
) -> tuple[OrganizationApiKey, str]:
    """Returns (row, full_key) -- full_key is the only time the complete
    secret ever exists outside this function's local scope; the caller
    (the management router) must return it in the response body and
    never persist or log it."""
    full_key, prefix, hashed_secret = generate_api_key()
    api_key = OrganizationApiKey(
        organization_id=organization_id,
        name=name,
        description=description,
        prefix=prefix,
        hashed_secret=hashed_secret,
        permissions=json.dumps(sorted(p.value for p in permissions)),
        created_by=actor.id,
        expires_at=expires_at,
    )
    db.add(api_key)
    db.flush()
    record_api_key_action(
        db,
        organization_id=organization_id,
        action=ApiKeyAuditAction.key_created,
        api_key_id=api_key.id,
        actor=actor,
        client_ip=client_ip,
        details={"name": name, "permissions": sorted(p.value for p in permissions)},
    )
    db.commit()
    db.refresh(api_key)
    return api_key, full_key


def list_api_keys_in_org(db: Session, organization_id: str) -> list[OrganizationApiKey]:
    return list(
        db.scalars(
            select(OrganizationApiKey)
            .where(OrganizationApiKey.organization_id == organization_id)
            .order_by(OrganizationApiKey.created_at.desc())
        ).all()
    )


def get_api_key_in_org(db: Session, organization_id: str, api_key_id: str) -> OrganizationApiKey:
    api_key = db.scalar(
        select(OrganizationApiKey).where(
            OrganizationApiKey.id == api_key_id,
            OrganizationApiKey.organization_id == organization_id,
        )
    )
    if api_key is None:
        raise ApiKeyNotFoundError(api_key_id)
    return api_key


def find_api_key_by_prefix(db: Session, prefix: str) -> OrganizationApiKey | None:
    """Used only by app.api_key_auth -- deliberately does NOT filter out
    revoked/expired rows (the caller needs to distinguish "no such key"
    from "this exact key, but revoked/expired" to log the right audit
    event and give a still-generic, but internally accurate, 401)."""
    return db.scalar(select(OrganizationApiKey).where(OrganizationApiKey.prefix == prefix))


def revoke_api_key(
    db: Session, api_key: OrganizationApiKey, actor: User, *, client_ip: str | None = None
) -> OrganizationApiKey:
    """Idempotent -- revoking an already-revoked key just re-confirms the
    same terminal state rather than erroring, matching this codebase's
    established convention for one-way lifecycle transitions (e.g.
    Product.active's archive)."""
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
        api_key.revoked_by = actor.id
        record_api_key_action(
            db,
            organization_id=api_key.organization_id,
            action=ApiKeyAuditAction.key_revoked,
            api_key_id=api_key.id,
            actor=actor,
            client_ip=client_ip,
        )
        db.commit()
        db.refresh(api_key)
    return api_key


def rotate_api_key(
    db: Session, api_key: OrganizationApiKey, actor: User, *, client_ip: str | None = None
) -> tuple[OrganizationApiKey, str]:
    """Revokes `api_key` and creates a brand-new row with the same name/
    description/permissions/expiration -- never mutates the old row's
    prefix/hashed_secret in place, so its history (created_at, and
    last_used_at up to the moment of rotation) stays exactly as it was.
    Returns (new_row, new_full_key)."""
    permissions = frozenset(
        p for p in ApiKeyPermission if p.value in json.loads(api_key.permissions)
    )
    api_key.revoked_at = datetime.now(timezone.utc)
    api_key.revoked_by = actor.id
    db.flush()

    full_key, prefix, hashed_secret = generate_api_key()
    new_key = OrganizationApiKey(
        organization_id=api_key.organization_id,
        name=api_key.name,
        description=api_key.description,
        prefix=prefix,
        hashed_secret=hashed_secret,
        permissions=api_key.permissions,
        created_by=actor.id,
        expires_at=api_key.expires_at,
    )
    db.add(new_key)
    db.flush()

    record_api_key_action(
        db,
        organization_id=api_key.organization_id,
        action=ApiKeyAuditAction.key_rotated,
        api_key_id=new_key.id,
        actor=actor,
        client_ip=client_ip,
        details={"rotated_from_key_id": api_key.id, "permissions": sorted(p.value for p in permissions)},
    )
    db.commit()
    db.refresh(new_key)
    return new_key, full_key


def touch_api_key_last_used(db: Session, api_key: OrganizationApiKey, client_ip: str | None) -> None:
    """Updates last_used_at/last_used_ip, but only when the existing
    value is missing or older than LAST_USED_TOUCH_INTERVAL.

    Why throttle: a busy integration can call the API many times per
    minute; writing last_used_at on literally every request would turn
    every authenticated call into two writes (the actual mutation, if
    any, plus this one) even for pure GETs that would otherwise be
    read-only, and would contend on the same row check_limit() may
    already be locking for a write request. A 5-minute granularity is
    more than precise enough for "is this key still being used" (the
    only thing last_used_at is for -- see the management UI) while
    cutting the write rate by roughly two orders of magnitude for any
    integration polling more often than every few minutes."""
    now = datetime.now(timezone.utc)
    if api_key.last_used_at is not None and now - _aware(api_key.last_used_at) < LAST_USED_TOUCH_INTERVAL:
        return
    api_key.last_used_at = now
    api_key.last_used_ip = client_ip
    db.commit()
