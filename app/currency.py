"""Currency resolution and formatting.

Organization.currency_code drives which code is shown across the PDF and
email templates. Adding a new supported currency means updating
SUPPORTED_CURRENCIES — call sites don't change.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Organization

DEFAULT_CURRENCY_CODE = "USD"
SUPPORTED_CURRENCIES = ("USD", "UYU", "EUR")


def get_currency_code(organization: "Organization | None" = None) -> str:
    """Returns the ISO 4217 currency code to display.

    Falls back to the safe default if no organization is given, or its
    currency_code is somehow missing/unrecognized.
    """
    code = getattr(organization, "currency_code", None) if organization is not None else None
    return code if code in SUPPORTED_CURRENCIES else DEFAULT_CURRENCY_CODE


def format_amount(amount: Decimal, currency_code: str | None = None) -> str:
    """Formats a monetary amount with its currency code, e.g. "USD 1,234.56"."""
    code = currency_code if currency_code in SUPPORTED_CURRENCIES else DEFAULT_CURRENCY_CODE
    return f"{code} {amount:,.2f}"
