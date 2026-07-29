"""How often a Subscription's current_period_start/end renews. Kept as
its own tiny enum (rather than inlined as a plain string check) so a
future third period (e.g. "quarterly") is a one-line addition here plus a
new branch in app.billing.service.BillingService's period-length lookup,
never a string literal duplicated across callers.
"""

from enum import Enum


class BillingPeriod(str, Enum):
    monthly = "monthly"
    yearly = "yearly"
