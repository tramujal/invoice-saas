"""Organization-local "today," for every due-date comparison in the app.

Due dates are stored as plain calendar dates (no time-of-day), so comparing
one against "today" must use the SAME calendar day the organization itself
would consider it to be -- not the server's UTC day, which can be a day off
right around midnight for any organization not in UTC. This is the single
place that conversion happens; every other module (effective status,
invoice creation validation, the reminders job, insights, assistant
context) calls this instead of computing its own "today."
"""

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from app.models import Organization

DEFAULT_TIMEZONE = "UTC"


def get_organization_today(organization: "Organization | None") -> date:
    """Returns "today" as a calendar date in the organization's configured
    IANA timezone. Falls back to UTC if the organization is missing or its
    stored timezone string is somehow invalid (e.g. hand-edited data) --
    mirrors app.localization.get_language's same defensive-fallback style,
    never raises."""
    tz_name = getattr(organization, "timezone", None) or DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(timezone.utc).astimezone(tz).date()
