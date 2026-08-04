"""DB query helpers for the experimental WhatsApp assistant (Phase 23) --
the only module that runs a `select`/`insert` against WhatsAppIdentity/
WhatsAppInboundMessage. app.whatsapp.service and the routers call these
rather than building queries inline, mirroring every other feature's
service-layer convention in this codebase.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMember, User, WhatsAppIdentity, WhatsAppInboundMessage
from app.membership_status import MembershipStatus
from app.organization_status import OrganizationStatus
from app.user_status import UserStatus
from app.whatsapp_identity_status import WhatsAppIdentityStatus


def get_verified_identity_by_phone(db: Session, provider: str, normalized_phone_number: str) -> WhatsAppIdentity | None:
    """The one lookup every inbound message resolution starts from --
    scoped to `verified` only (a `pending`/`disabled` row is never treated
    as an authenticated identity, see app.whatsapp.service)."""
    return db.scalar(
        select(WhatsAppIdentity).where(
            WhatsAppIdentity.provider == provider,
            WhatsAppIdentity.normalized_phone_number == normalized_phone_number,
            WhatsAppIdentity.status == WhatsAppIdentityStatus.verified.value,
        )
    )


def get_any_identity_by_phone(db: Session, provider: str, normalized_phone_number: str) -> WhatsAppIdentity | None:
    """Unlike get_verified_identity_by_phone above, returns a `pending`
    row too -- used only by the linking-code-confirmation path, which by
    definition looks up a not-yet-verified row."""
    return db.scalar(
        select(WhatsAppIdentity).where(
            WhatsAppIdentity.provider == provider,
            WhatsAppIdentity.normalized_phone_number == normalized_phone_number,
        )
    )


def get_identity_in_org(db: Session, organization_id: str, identity_id: str) -> WhatsAppIdentity | None:
    return db.scalar(
        select(WhatsAppIdentity).where(
            WhatsAppIdentity.id == identity_id,
            WhatsAppIdentity.organization_id == organization_id,
        )
    )


def get_identity_for_user_in_org(db: Session, organization_id: str, user_id: str) -> WhatsAppIdentity | None:
    """A user's own current (pending or verified) link in this
    organization, if any -- used by the "link/revoke own number" self-
    serve flow. Never returns a `disabled` row: a revoked link is no
    longer "the user's current identity," it's history."""
    return db.scalar(
        select(WhatsAppIdentity).where(
            WhatsAppIdentity.organization_id == organization_id,
            WhatsAppIdentity.user_id == user_id,
            WhatsAppIdentity.status != WhatsAppIdentityStatus.disabled.value,
        )
    )


def list_identities_for_org(db: Session, organization_id: str) -> list[tuple[WhatsAppIdentity, str]]:
    """Every non-disabled identity in this organization, joined with the
    linked user's email for display -- the Settings page's "linked
    users" list. Excludes `disabled` rows: a revoked link isn't shown as
    still occupying a seat."""
    rows = db.execute(
        select(WhatsAppIdentity, User.email)
        .join(User, User.id == WhatsAppIdentity.user_id)
        .where(
            WhatsAppIdentity.organization_id == organization_id,
            WhatsAppIdentity.status != WhatsAppIdentityStatus.disabled.value,
        )
        .order_by(WhatsAppIdentity.created_at.desc())
    ).all()
    return [(identity, email) for identity, email in rows]


def list_command_history(db: Session, organization_id: str, *, limit: int = 20) -> list[WhatsAppInboundMessage]:
    return list(
        db.scalars(
            select(WhatsAppInboundMessage)
            .where(WhatsAppInboundMessage.organization_id == organization_id)
            .order_by(WhatsAppInboundMessage.created_at.desc())
            .limit(limit)
        ).all()
    )


def is_message_already_processed(db: Session, provider: str, message_id: str) -> bool:
    """Idempotency/replay-protection check -- called BEFORE any processing
    of an inbound message. A message the bridge (or a duplicate WhatsApp
    delivery) posts twice is only ever acted on once."""
    return (
        db.scalar(
            select(WhatsAppInboundMessage.id).where(
                WhatsAppInboundMessage.provider == provider,
                WhatsAppInboundMessage.message_id == message_id,
            )
        )
        is not None
    )


def record_inbound_message(
    db: Session,
    *,
    provider: str,
    message_id: str,
    organization_id: str | None,
    user_id: str | None,
    whatsapp_identity_id: str | None,
    message_type: str,
    command_action: str | None,
    status: str,
    failure_code: str | None = None,
) -> WhatsAppInboundMessage:
    """Inserts the one persisted record of an inbound message -- see
    WhatsAppInboundMessage's own docstring for why this never includes
    raw message/transcript text. Caller commits."""
    record = WhatsAppInboundMessage(
        provider=provider,
        message_id=message_id,
        organization_id=organization_id,
        user_id=user_id,
        whatsapp_identity_id=whatsapp_identity_id,
        message_type=message_type,
        command_action=command_action,
        status=status,
        failure_code=failure_code,
    )
    db.add(record)
    return record


def is_user_active_member(db: Session, organization_id: str, user_id: str) -> bool:
    """Re-checks, from scratch, every condition a browser request would
    already imply via require_org_member -- an inbound WhatsApp message
    has no session/JWT, so this is the one place that re-derives "is this
    still a legitimate, currently-active user of a currently-active
    organization" from the live DB, exactly as strictly as the web app
    does. Never trusts a cached WhatsAppIdentity row alone -- a user
    disabled or removed after linking their phone loses WhatsApp access
    on their very next message, with no separate revocation step needed."""
    user = db.get(User, user_id)
    if user is None or user.status == UserStatus.disabled.value:
        return False

    organization = db.get(Organization, organization_id)
    if organization is None or organization.status == OrganizationStatus.suspended.value:
        return False

    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == MembershipStatus.active.value,
        )
    )
    return membership is not None


def touch_identity_last_message(db: Session, identity: WhatsAppIdentity) -> None:
    identity.last_message_at = datetime.now(timezone.utc)
