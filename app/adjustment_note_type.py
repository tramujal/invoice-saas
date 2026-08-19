"""Whether an adjustment note reduces or increases the economic value of
its source invoice.

Deliberately a discriminator on ONE shared model rather than two parallel
models: credit and debit notes have identical structure, identical tax
handling, identical numbering mechanics and identical delivery needs.
They differ only in the sign of their economic effect and in whether
line-level source limits apply -- see docs/credit_debit_notes.md.

A credit note is NEVER a negative invoice, and a debit note is NEVER a
negative credit note. Both carry positive line amounts; the sign lives
here, in the type, and is applied once by
app.services.adjustment_notes.signed_total.
"""

from enum import Enum


class AdjustmentNoteType(str, Enum):
    credit = "credit"
    debit = "debit"
