"""Currency resolution and formatting.

Organization.currency_code is the default for *new* invoices;
Invoice.currency_code is what's actually displayed on that invoice's PDF,
email, and every read endpoint — permanently pinned at creation time.
Adding a new supported currency means updating SUPPORTED_CURRENCIES — call
sites don't change.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Customer, Invoice, Organization

DEFAULT_CURRENCY_CODE = "USD"
SUPPORTED_CURRENCIES = ("USD", "UYU", "EUR")


def resolve_default_currency_code(
    customer: "Customer | None", organization: "Organization"
) -> str:
    """Single source of truth for what currency a *new* invoice should
    default to before any explicit override on the create request.

    Currently this is always the organization's default, regardless of
    customer. It takes `customer` as a parameter (rather than just
    `organization`) so that a future customer-level preferred currency only
    requires changing the body of this function — e.g. preferring
    `customer.preferred_currency_code` when set — with no changes needed at
    its call site in invoice creation, and no change to the invoice
    creation payload/API shape (an explicit `currency_code` on the request
    still wins over whatever this returns).
    """
    return get_currency_code(organization)


def get_currency_code(organization: "Organization | Invoice | None" = None) -> str:
    """Returns the ISO 4217 currency code to display.

    Accepts either an Organization (its configured default) or an Invoice
    (its permanently-pinned currency) — both just need a .currency_code
    attribute, so this one function serves both without duplication. Falls
    back to the safe default if nothing is given, or the value is somehow
    missing/unrecognized.
    """
    code = getattr(organization, "currency_code", None) if organization is not None else None
    return code if code in SUPPORTED_CURRENCIES else DEFAULT_CURRENCY_CODE


def format_amount(amount: Decimal, currency_code: str | None = None) -> str:
    """Formats a monetary amount with its currency code, e.g. "USD 1,234.56"."""
    code = currency_code if currency_code in SUPPORTED_CURRENCIES else DEFAULT_CURRENCY_CODE
    return f"{code} {amount:,.2f}"
