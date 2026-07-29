"""Subscription lifecycle states -- see app.billing.service.BillingService
for the centralized set of transitions that move a Subscription between
these (never written to directly anywhere else, the same discipline
app.job_status.JobStatus documents for BackgroundJob).

`past_due` and `paused` exist now specifically so a future payment-
provider integration has somewhere to land a failed/retrying charge or a
provider-side pause without a schema change -- this phase never sets
either one itself (no provider is integrated yet), but the model already
supports them.
"""

from enum import Enum


class SubscriptionStatus(str, Enum):
    trialing = "trialing"
    active = "active"
    past_due = "past_due"
    paused = "paused"
    canceled = "canceled"
    expired = "expired"
    inactive = "inactive"
