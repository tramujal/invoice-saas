"""The single source of truth for whether an invoice is effectively
pending, paid, or overdue -- every surface (API responses, the PDF, emails,
the dashboard, Business Insights, the AI assistant) calls this, never its
own copy of the logic.

Paid always stays an explicit, stored fact. Everything else is derived
from due_date once one exists:
- due_date is set: overdue iff due_date < today (org-local), else pending
  -- the stored payment_status value is ignored here entirely, since the
  date already proves the answer.
- due_date is NOT set (every historical invoice created before this
  feature existed, since due_date is never backfilled): falls back to
  whatever payment_status already says, completely unchanged -- this is
  what keeps old invoices' displayed status frozen exactly as it was
  rather than silently reclassifying them.
"""

from datetime import date
from typing import TYPE_CHECKING

from app.payment_status import PaymentStatus

if TYPE_CHECKING:
    from app.models import Invoice


def get_effective_payment_status(invoice: "Invoice", today_local: date) -> PaymentStatus:
    if invoice.payment_status == PaymentStatus.paid.value:
        return PaymentStatus.paid

    if invoice.due_date is not None:
        return PaymentStatus.overdue if invoice.due_date < today_local else PaymentStatus.pending

    # No due_date on file -- nothing here can improve on whatever is
    # already stored, so it passes through unchanged.
    return PaymentStatus(invoice.payment_status)
