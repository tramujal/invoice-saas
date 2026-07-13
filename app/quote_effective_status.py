"""The single source of truth for whether a quote is effectively still a
draft, sent, accepted, rejected, expired, or converted -- every surface
(API responses, PDF, email, dashboard, insights, assistant) calls this,
never its own copy of the logic. Mirrors app.effective_status's exact
three-branch shape for invoice overdue-ness.

accepted/rejected/converted are explicit, stored facts and always win
outright once set -- they represent something that actually happened
(a customer decision, or a completed conversion) and can never be
retroactively overridden by a mere date comparison.

Otherwise, expired is derived from expiry_date once one exists:
- expiry_date is set and < today (org-local): expired -- regardless of
  whether the stored status is still "draft" or "sent". No job ever
  writes status="expired"; this is computed fresh on every read.
- expiry_date is NOT set, or is set but not yet passed: the stored status
  (draft/sent) passes through unchanged.
"""

from datetime import date
from typing import TYPE_CHECKING

from app.quote_status import QuoteStatus

if TYPE_CHECKING:
    from app.models import Quote

_TERMINAL_STATUSES = {
    QuoteStatus.accepted.value,
    QuoteStatus.rejected.value,
    QuoteStatus.converted.value,
}


def get_effective_quote_status(quote: "Quote", today_local: date) -> QuoteStatus:
    if quote.status in _TERMINAL_STATUSES:
        return QuoteStatus(quote.status)

    if quote.expiry_date is not None and quote.expiry_date < today_local:
        return QuoteStatus.expired

    return QuoteStatus(quote.status)
