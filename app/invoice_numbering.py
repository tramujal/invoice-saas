"""Human-friendly invoice number formatting.

The database stores a plain sequential integer per organization
(Invoice.invoice_number); this is the single place that turns it into the
"INV-000006" form shown to users, so the API schema and the PDF stay in sync.
"""

INVOICE_NUMBER_PREFIX = "INV-"
INVOICE_NUMBER_PADDING = 6


def format_invoice_number(number: int) -> str:
    return f"{INVOICE_NUMBER_PREFIX}{number:0{INVOICE_NUMBER_PADDING}d}"


def parse_invoice_number(value: str) -> int | None:
    """Reverse of format_invoice_number: extracts the integer invoice number
    from a term like "5", "000005", or "INV-000005". Returns None if, after
    stripping an optional INV- prefix, the term isn't purely numeric (e.g.
    it's a name search) -- callers must treat that as "not a number lookup",
    never as "invoice 0"."""
    term = value.strip()
    if term.lower().startswith(INVOICE_NUMBER_PREFIX.lower()):
        term = term[len(INVOICE_NUMBER_PREFIX):]
    term = term.lstrip("0") or "0"
    return int(term) if term.isdigit() else None
