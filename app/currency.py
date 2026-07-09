"""Currency resolution.

Nothing in the data model has a per-invoice or per-organization currency
field yet. This module is the single place that decides what currency to
display, so when that field is added later, only get_currency_code() needs
to change — no hardcoded currency strings to hunt down across templates.
"""

DEFAULT_CURRENCY_CODE = "USD"


def get_currency_code() -> str:
    """Returns the ISO 4217 currency code to display.

    Always returns the safe fallback for now. Once a real currency field
    exists on Invoice or Organization, update this function's body to read
    it — callers won't need to change.
    """
    return DEFAULT_CURRENCY_CODE
