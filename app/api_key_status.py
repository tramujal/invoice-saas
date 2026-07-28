"""The single source of truth for an API key's effective status.

Mirrors app.effective_status's own approach: status is never a redundant
stored column that could drift from the raw facts it summarizes -- it's
always derived, at read time, from revoked_at/expires_at (matching how
Product.active, not a second "status" column, is the one source of
truth for a product's archived state elsewhere in this codebase).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import OrganizationApiKey


class ApiKeyStatus(str, Enum):
    active = "active"
    revoked = "revoked"
    expired = "expired"


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True)
    # columns (Postgres returns aware ones) -- normalize before comparing,
    # same convention as app.routers.assistant_actions's own _aware.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def get_effective_api_key_status(api_key: "OrganizationApiKey") -> ApiKeyStatus:
    if api_key.revoked_at is not None:
        return ApiKeyStatus.revoked
    if api_key.expires_at is not None and _aware(api_key.expires_at) <= datetime.now(timezone.utc):
        return ApiKeyStatus.expired
    return ApiKeyStatus.active
