"""Human-readable title/body rendering for each app.webhook_event_type
.WebhookEventType -- the one place notification copy is generated from an
event's payload, keeping app.notifications.service free of per-event-type
string formatting.

A `payload` here is always the exact same dict
app.services.webhook_events.record_webhook_event already received (a
Response-model dump captured at the domain mutation's own commit
boundary) -- this module only ever reads from it, never re-fetches or
re-derives anything from the database itself. Every renderer accesses
payload fields defensively (`.get`, with a fallback) because the schema
of a Response-model dump can, in principle, evolve independently of this
module.

Adding a new WebhookEventType does not require a renderer here: an event
type with no entry falls back to a generic, still-readable title/body
(see render_notification_copy) rather than raising -- but adding one is
recommended so notifications read naturally.
"""

from collections.abc import Callable

from app.webhook_event_type import WebhookEventType

_Renderer = Callable[[dict], tuple[str, str]]


def _customer_label(payload: dict) -> str:
    return payload.get("name") or "A customer"


def _quote_label(payload: dict) -> str:
    return payload.get("quote_number") or "A quote"


def _invoice_label(payload: dict) -> str:
    return payload.get("invoice_number") or "An invoice"


def _product_label(payload: dict) -> str:
    return payload.get("name") or "A product"


def _customer_created(payload: dict) -> tuple[str, str]:
    return "Customer created", f"{_customer_label(payload)} was added as a customer."


def _customer_updated(payload: dict) -> tuple[str, str]:
    return "Customer updated", f"{_customer_label(payload)}'s details were updated."


def _customer_deleted(payload: dict) -> tuple[str, str]:
    return "Customer deleted", f"{_customer_label(payload)} was deleted."


def _product_created(payload: dict) -> tuple[str, str]:
    return "Product created", f"{_product_label(payload)} was added to your catalog."


def _product_updated(payload: dict) -> tuple[str, str]:
    return "Product updated", f"{_product_label(payload)} was updated."


def _product_archived(payload: dict) -> tuple[str, str]:
    return "Product archived", f"{_product_label(payload)} was archived."


def _product_restored(payload: dict) -> tuple[str, str]:
    return "Product restored", f"{_product_label(payload)} was restored."


def _quote_created(payload: dict) -> tuple[str, str]:
    return "Quote created", f"Quote {_quote_label(payload)} was created."


def _quote_updated(payload: dict) -> tuple[str, str]:
    return "Quote updated", f"Quote {_quote_label(payload)} was updated."


def _quote_deleted(payload: dict) -> tuple[str, str]:
    return "Quote deleted", f"Quote {_quote_label(payload)} was deleted."


def _quote_sent(payload: dict) -> tuple[str, str]:
    customer = payload.get("customer_name") or "the customer"
    return "Quote sent", f"Quote {_quote_label(payload)} was sent to {customer}."


def _quote_accepted(payload: dict) -> tuple[str, str]:
    return "Quote accepted", f"Quote {_quote_label(payload)} was accepted."


def _quote_rejected(payload: dict) -> tuple[str, str]:
    return "Quote rejected", f"Quote {_quote_label(payload)} was rejected."


def _quote_converted(payload: dict) -> tuple[str, str]:
    return "Quote converted", f"Quote {_quote_label(payload)} was converted into an invoice."


def _invoice_created(payload: dict) -> tuple[str, str]:
    return "Invoice created", f"Invoice {_invoice_label(payload)} was created."


def _invoice_updated(payload: dict) -> tuple[str, str]:
    return "Invoice updated", f"Invoice {_invoice_label(payload)} was updated."


def _invoice_sent(payload: dict) -> tuple[str, str]:
    customer = payload.get("customer_name") or "the customer"
    return "Invoice sent", f"Invoice {_invoice_label(payload)} was sent to {customer}."


def _organization_plan_changed(payload: dict) -> tuple[str, str]:
    new_plan = payload.get("new_plan") or {}
    plan_label = new_plan.get("code") or "a new plan"
    return "Plan changed", f"Your organization's plan changed to {plan_label}."


_RENDERERS: dict[WebhookEventType, _Renderer] = {
    WebhookEventType.customer_created: _customer_created,
    WebhookEventType.customer_updated: _customer_updated,
    WebhookEventType.customer_deleted: _customer_deleted,
    WebhookEventType.product_created: _product_created,
    WebhookEventType.product_updated: _product_updated,
    WebhookEventType.product_archived: _product_archived,
    WebhookEventType.product_restored: _product_restored,
    WebhookEventType.quote_created: _quote_created,
    WebhookEventType.quote_updated: _quote_updated,
    WebhookEventType.quote_deleted: _quote_deleted,
    WebhookEventType.quote_sent: _quote_sent,
    WebhookEventType.quote_accepted: _quote_accepted,
    WebhookEventType.quote_rejected: _quote_rejected,
    WebhookEventType.quote_converted: _quote_converted,
    WebhookEventType.invoice_created: _invoice_created,
    WebhookEventType.invoice_updated: _invoice_updated,
    WebhookEventType.invoice_sent: _invoice_sent,
    WebhookEventType.organization_plan_changed: _organization_plan_changed,
}


def render_notification_copy(event_type: WebhookEventType, payload: dict) -> tuple[str, str]:
    renderer = _RENDERERS.get(event_type)
    if renderer is None:
        return event_type.value, "An event occurred in your organization."
    return renderer(payload)
