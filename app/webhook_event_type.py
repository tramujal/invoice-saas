"""The complete, authoritative catalog of domain events this app can
raise -- despite the name (kept for historical/API-compatibility reasons:
its string values are already what a receiving webhook endpoint's
`subscribed_events` list matches against), this enum is, since Phase 20,
the shared event vocabulary for ALL three notification channels this app
supports, not webhooks alone. See app.notifications.service.emit_event,
the single call site every event in this enum is actually raised from
(itself a thin wrapper around app.services.webhook_events
.record_webhook_event for the webhook channel specifically, unchanged
since Phase 15B -- see that module's docstring for the full emission
map).

Every member is `"{domain}.{transition}"`, matching the payload's own
`event` field verbatim -- this is the value a receiving webhook endpoint's
`subscribed_events` list is matched against (or the wildcard `"*"`, see
WebhookEndpoint.subscribed_events), and the value shown in the management
UI's event-subscription selector, grouped by the part before the dot.

Adding a new event type is exactly two steps: add the member here, and add
the one emit_event(...) call at its real, authoritative transaction
boundary -- never a third place, and never inferred from an existing
event by string manipulation. A third, optional step -- adding a renderer
to app.notifications.copy -- gives the in-app/email channels natural
copy instead of a generic fallback string.
"""

from enum import Enum


class WebhookEventType(str, Enum):
    customer_created = "customer.created"
    customer_updated = "customer.updated"
    customer_deleted = "customer.deleted"

    product_created = "product.created"
    product_updated = "product.updated"
    product_archived = "product.archived"
    product_restored = "product.restored"

    quote_created = "quote.created"
    quote_updated = "quote.updated"
    quote_deleted = "quote.deleted"
    quote_sent = "quote.sent"
    quote_accepted = "quote.accepted"
    quote_rejected = "quote.rejected"
    quote_converted = "quote.converted"

    invoice_created = "invoice.created"
    invoice_updated = "invoice.updated"
    invoice_sent = "invoice.sent"
    # Phase 29 -- credit/debit notes. One event family for both types;
    # the payload's note_type distinguishes them, so a subscriber that
    # cares about "any adjustment to an invoice" needs one subscription
    # rather than two that must be kept in sync.
    adjustment_note_created = "adjustment_note.created"
    adjustment_note_issued = "adjustment_note.issued"
    adjustment_note_voided = "adjustment_note.voided"
    adjustment_note_sent = "adjustment_note.sent"

    organization_plan_changed = "organization.plan_changed"

    # Phase 24.3 -- the AI Financial Advisor's report lifecycle. Raised
    # from app.financial_intelligence.recommendations at the exact
    # transaction boundary of each transition (request, success, failure)
    # -- never inferred elsewhere. There is deliberately no
    # "financial_insight.expired" member: expiry is only ever noticed
    # passively, the next time a report is requested and found stale
    # (see app.financial_intelligence.cache.find_reusable_report) --
    # there is no background sweep that would have an authoritative
    # moment to raise such an event from.
    financial_insight_requested = "financial_insight.requested"
    financial_insight_generated = "financial_insight.generated"
    financial_insight_failed = "financial_insight.failed"


# Grouping key for the frontend's event-subscription selector (the part of
# the value before the dot) -- computed here, once, rather than re-parsed
# by every caller.
def event_domain(event_type: "WebhookEventType") -> str:
    return event_type.value.split(".", 1)[0]
