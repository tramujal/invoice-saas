"""The complete, authoritative catalog of events this app can emit as
outbound webhooks -- see app.services.webhook_events.record_webhook_event,
the single call site every event in this enum is actually raised from (see
that module's docstring for the full emission map).

Every member is `"{domain}.{transition}"`, matching the payload's own
`event` field verbatim -- this is the value a receiving endpoint's
`subscribed_events` list is matched against (or the wildcard `"*"`, see
WebhookEndpoint.subscribed_events), and the value shown in the management
UI's event-subscription selector, grouped by the part before the dot.

Adding a new event type is exactly two steps: add the member here, and add
the one record_webhook_event(...) call at its real, authoritative
transaction boundary -- never a third place, and never inferred from an
existing event by string manipulation.
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

    organization_plan_changed = "organization.plan_changed"


# Grouping key for the frontend's event-subscription selector (the part of
# the value before the dot) -- computed here, once, rather than re-parsed
# by every caller.
def event_domain(event_type: "WebhookEventType") -> str:
    return event_type.value.split(".", 1)[0]
