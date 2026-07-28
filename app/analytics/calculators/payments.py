"""Average payment time -- how long, on average, an invoice takes to go
from created to paid.

Not computable today: Invoice has no `paid_at` (or `updated_at`) column,
so there is no stored moment recording WHEN payment_status flipped to
"paid," only that it currently is (see app.assistant_context's own note:
"Invoice has no paid_at either"). Fabricating a proxy -- e.g. treating
due_date as a payment date, or using created_at as a stand-in -- would
silently report a plausible-looking but meaningless number, which is
worse than an honest gap. This calculator exists now, with a real,
independently-testable return shape, specifically so that the moment a
future phase adds a genuine `paid_at` timestamp (set wherever
payment_status is written to "paid" -- see app.routers.invoices' status-
update endpoint), only this one function's body needs to change; every
caller already treats `available` as something it must check.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

NOT_AVAILABLE_REASON = (
    "Invoice has no paid_at timestamp -- average payment time cannot be "
    "computed until one is added."
)


@dataclass(frozen=True)
class AveragePaymentTime:
    available: bool
    average_days: float | None
    reason: str | None


def get_average_payment_time(db: Session, organization_id: str) -> AveragePaymentTime:
    return AveragePaymentTime(available=False, average_days=None, reason=NOT_AVAILABLE_REASON)
