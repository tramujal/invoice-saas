"""Currency resolution and formatting.

Organization.currency_code is the default for *new* invoices;
Invoice.currency_code is what's actually displayed on that invoice's PDF,
email, and every read endpoint — permanently pinned at creation time.
Adding a new supported currency means updating SUPPORTED_CURRENCIES — call
sites don't change.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, Sequence

if TYPE_CHECKING:
    from app.models import Invoice, Organization, Product

DEFAULT_CURRENCY_CODE = "USD"
SUPPORTED_CURRENCIES = ("USD", "UYU", "EUR")


class CurrencyRequiredError(Exception):
    """Raised when a document's currency can't be inferred: no explicit
    currency_code was given, and no line item is linked to a product (i.e.
    every line is a manual line, which carries no currency of its own)."""


class ProductCurrencyMismatchError(Exception):
    """Raised when a line item's product currency doesn't match the
    document's currency (explicit or already inferred from an earlier
    line)."""

    def __init__(self, product_name: str, product_currency: str, document_currency: str):
        self.product_name = product_name
        self.product_currency = product_currency
        self.document_currency = document_currency
        super().__init__(
            f"Product '{product_name}' is priced in {product_currency}, "
            f"but this document is in {document_currency}."
        )


class _HasProductId(Protocol):
    product_id: str | None


def resolve_document_currency_code(
    requested_currency_code: str | None,
    line_items: Sequence[_HasProductId],
    resolved_products_by_id: "dict[str, Product]",
) -> str:
    """Single source of truth for resolving a document's (invoice or
    quote's) currency from an optional explicit override plus its line
    items' products.

    - If `requested_currency_code` is given, every product-linked line must
      match it (raises ProductCurrencyMismatchError on the first mismatch).
    - If not given, the first product-linked line's product currency
      becomes the baseline, and every other product-linked line must match
      it.
    - Manual lines (product_id is None) carry no currency of their own in
      the schema — they're validated only insofar as the single top-level
      currency_code they implicitly belong to must match every product-
      linked line's currency too.
    - If no baseline can be established at all (no requested currency, no
      product-linked line), raises CurrencyRequiredError.

    `resolved_products_by_id` must already contain every product referenced
    by `line_items` — callers fetch these anyway to validate product
    existence, so this function takes no db/organization_id and issues no
    queries of its own.
    """
    baseline = requested_currency_code
    for line in line_items:
        if line.product_id is None:
            continue
        product = resolved_products_by_id[line.product_id]
        if baseline is None:
            baseline = product.currency_code
        elif product.currency_code != baseline:
            raise ProductCurrencyMismatchError(product.name, product.currency_code, baseline)
    if baseline is None:
        raise CurrencyRequiredError()
    return baseline


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
