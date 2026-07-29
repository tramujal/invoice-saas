"""Every kind of change app.billing.service.BillingService can make to a
Subscription, recorded as a SubscriptionEvent row. This is subscription
HISTORY, not the platform Audit Log (app.models.PlatformAuditLog) --
Audit Log answers "who did what" (a platform admin's own actions);
SubscriptionEvent answers "what happened to this subscription over
time," including system-triggered transitions (trial_expired,
subscription_expired) that have no human actor at all.

Phase 18 adds three provider-driven members (`provider_linked`,
`provider_subscription_updated`, `payment_failed`) -- purely additive,
same backward-compatible convention Phase 17B used when extending
LimitedResource: every existing member/value is untouched, so every
existing SubscriptionEvent row and every existing test that asserts on
one of the original event types keeps working unchanged.
"""

from enum import Enum


class SubscriptionEventType(str, Enum):
    subscription_created = "subscription_created"
    trial_started = "trial_started"
    trial_expired = "trial_expired"
    subscription_activated = "subscription_activated"
    subscription_renewed = "subscription_renewed"
    subscription_canceled = "subscription_canceled"
    subscription_reactivated = "subscription_reactivated"
    subscription_resumed = "subscription_resumed"
    plan_upgraded = "plan_upgraded"
    plan_downgraded = "plan_downgraded"
    billing_period_changed = "billing_period_changed"
    subscription_expired = "subscription_expired"
    manual_adjustment = "manual_adjustment"
    # Phase 18 additions -- see app.billing.service.BillingService
    # .attach_provider_subscription / .sync_period_from_provider /
    # .mark_past_due.
    provider_linked = "provider_linked"
    provider_subscription_updated = "provider_subscription_updated"
    payment_failed = "payment_failed"
