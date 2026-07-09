"""Human-friendly invoice number formatting.

The database stores a plain sequential integer per organization
(Invoice.invoice_number); this is the single place that turns it into the
"INV-000006" form shown to users, so the API schema and the PDF stay in sync.
"""

INVOICE_NUMBER_PREFIX = "INV-"
INVOICE_NUMBER_PADDING = 6


def format_invoice_number(number: int) -> str:
    return f"{INVOICE_NUMBER_PREFIX}{number:0{INVOICE_NUMBER_PADDING}d}"
