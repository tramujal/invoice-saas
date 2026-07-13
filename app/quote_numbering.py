"""Human-friendly quote number formatting -- mirrors
app.invoice_numbering exactly, with a distinct prefix so a quote reference
and an invoice reference can never be confused with each other.
"""

QUOTE_NUMBER_PREFIX = "QUO-"
QUOTE_NUMBER_PADDING = 6


def format_quote_number(number: int) -> str:
    return f"{QUOTE_NUMBER_PREFIX}{number:0{QUOTE_NUMBER_PADDING}d}"


def parse_quote_number(value: str) -> int | None:
    """Reverse of format_quote_number: extracts the integer quote number
    from a term like "5", "000005", or "QUO-000005". Returns None if, after
    stripping an optional QUO- prefix, the term isn't purely numeric (e.g.
    it's a name search) -- callers must treat that as "not a number lookup",
    never as "quote 0"."""
    term = value.strip()
    if term.lower().startswith(QUOTE_NUMBER_PREFIX.lower()):
        term = term[len(QUOTE_NUMBER_PREFIX):]
    term = term.lstrip("0") or "0"
    return int(term) if term.isdigit() else None
