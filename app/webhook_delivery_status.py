"""Lifecycle of one WebhookDelivery row.

Deliberately only three states -- there is no "retrying" state, because
Phase 15B never executes an automatic retry (see
app.services.webhook_deliveries's module docstring): a delivery is either
still waiting for its first attempt, or it has already been attempted
exactly once and the outcome is final for that row. A future retry
(Phase 15C) creates a brand-new WebhookDelivery row rather than mutating
this one back to `pending` -- manual resend already establishes that
exact "new row per attempt" precedent (see
app.services.webhook_deliveries.resend_delivery).
"""

from enum import Enum


class WebhookDeliveryStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
