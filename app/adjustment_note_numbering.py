"""Human-friendly adjustment-note numbers -- mirrors
app.invoice_numbering / app.quote_numbering exactly, with distinct
prefixes per note type so a credit note, a debit note, an invoice and a
quote reference can never be confused with one another.

Credit and debit notes draw from SEPARATE per-organization sequences
(Organization.next_credit_note_number / next_debit_note_number), and
neither ever consumes an invoice number.

The prefixes are English-stable identifiers, exactly like INV-/QUO-:
they are part of the document's identity and must not change with the
reader's language. Spanish surfaces label the document "Nota de crédito"
while still showing CN-000001, for the same reason INV-000001 is not
translated to FAC-000001 today.
"""

from app.adjustment_note_type import AdjustmentNoteType

CREDIT_NOTE_NUMBER_PREFIX = "CN-"
DEBIT_NOTE_NUMBER_PREFIX = "DN-"
ADJUSTMENT_NOTE_NUMBER_PADDING = 6

_PREFIXES = {
    AdjustmentNoteType.credit: CREDIT_NOTE_NUMBER_PREFIX,
    AdjustmentNoteType.debit: DEBIT_NOTE_NUMBER_PREFIX,
}


def note_number_prefix(note_type: AdjustmentNoteType | str) -> str:
    return _PREFIXES[AdjustmentNoteType(note_type)]


def format_note_number(note_type: AdjustmentNoteType | str, number: int) -> str:
    return f"{note_number_prefix(note_type)}{number:0{ADJUSTMENT_NOTE_NUMBER_PADDING}d}"


def parse_note_number(note_type: AdjustmentNoteType | str, value: str) -> int | None:
    """Reverse of format_note_number. Returns None when the term isn't a
    number lookup (e.g. a customer-name search), never 0 -- matching
    parse_invoice_number's own contract."""
    term = value.strip()
    prefix = note_number_prefix(note_type)
    if term.lower().startswith(prefix.lower()):
        term = term[len(prefix):]
    term = term.lstrip("0") or "0"
    return int(term) if term.isdigit() else None
