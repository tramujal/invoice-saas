"""The lifecycle of an adjustment note.

Modelled on app.quote_status.QuoteStatus -- the only document lifecycle
this repository already has (invoices have none; they are final the
moment they exist). Deliberately minimal: three states, one forward
transition each, no reopening.

  draft  -> editable, inert. Affects NOTHING: not the adjusted invoice
            total, not receivables, not revenue, not forecasting.
  issued -> financially immutable and economically effective. This is
            the ONLY status any derived calculation ever counts.
  void   -> retained forever for audit, but economically inert again.
            Never deleted, never hidden from history.

There is no "paid" state: a note adjusts what is owed on its source
invoice, it is not itself settled. See docs/credit_debit_notes.md on why
correcting an issued note means voiding it and issuing another rather
than editing financial history in place.
"""

from enum import Enum


class AdjustmentNoteStatus(str, Enum):
    draft = "draft"
    issued = "issued"
    void = "void"

    @property
    def affects_invoice_economics(self) -> bool:
        """The single predicate every derived calculation asks. Keeping it
        here means "which statuses count" is decided in exactly one place
        rather than re-spelled as `status == "issued"` across analytics,
        receivables, forecasting and the API."""
        return self is AdjustmentNoteStatus.issued
