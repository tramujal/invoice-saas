"""Read/write access to the singleton PlatformSettings row -- see that
model's own docstring for why this is a typed table, not JSON key/value
storage, and why there's no caching layer here at all: every read in
this module goes straight to the database on every single call, with
zero staleness window -- the same "always re-check live state" contract
already established for organization suspension (app.deps.
_ensure_organization_active) and user disabling (app.deps.
get_current_user). A change made through PATCH /admin/settings is
visible to the very next call anywhere in the app, with no invalidation
step required.

get_effective_settings() is the read path nearly every enforcement point
in this app uses (deps.py, the AI/email factories, the reminder jobs,
public quote/invitation writes, registration); get_or_create_settings_row
is the one path that needs a live, mutable ORM row (the GET/PATCH
/admin/settings handlers).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PLATFORM_SETTINGS_SINGLETON_ID, PlatformSettings


@dataclass(frozen=True)
class SettingsSnapshot:
    maintenance_mode: bool
    registrations_enabled: bool
    ai_enabled: bool
    emails_enabled: bool
    invoice_reminders_enabled: bool
    quote_reminders_enabled: bool
    default_language: str
    default_currency: str


def get_or_create_settings_row(db: Session) -> PlatformSettings:
    """Returns the live, mutable singleton row, creating it with the
    model's own column defaults on first read. Callers that only need to
    read a few values and have no session of their own should use
    get_effective_settings() instead -- this is for callers that already
    have a request-scoped session open and may go on to mutate/commit the
    returned row."""
    existing = db.get(PlatformSettings, PLATFORM_SETTINGS_SINGLETON_ID)
    if existing is not None:
        return existing
    row = PlatformSettings(id=PLATFORM_SETTINGS_SINGLETON_ID)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _snapshot_from_row(row: PlatformSettings) -> SettingsSnapshot:
    return SettingsSnapshot(
        maintenance_mode=row.maintenance_mode,
        registrations_enabled=row.registrations_enabled,
        ai_enabled=row.ai_enabled,
        emails_enabled=row.emails_enabled,
        invoice_reminders_enabled=row.invoice_reminders_enabled,
        quote_reminders_enabled=row.quote_reminders_enabled,
        default_language=row.default_language,
        default_currency=row.default_currency,
    )


def get_effective_settings(db: Session | None = None) -> SettingsSnapshot:
    """The read path for every enforcement point in this app. Pass an
    existing session when the caller already has one open for this
    request (deps.py, the admin router, registration) to avoid opening a
    second connection; omit it entirely for call sites with no session
    of their own (the AI/email factories, the standalone reminder-job
    scripts), which get one opened and closed here immediately, for a
    single cheap read."""
    if db is not None:
        return _snapshot_from_row(get_or_create_settings_row(db))
    owned_db = SessionLocal()
    try:
        return _snapshot_from_row(get_or_create_settings_row(owned_db))
    finally:
        owned_db.close()
