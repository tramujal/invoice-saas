"""Human-readable, LOCALIZED title/body rendering for each
app.webhook_event_type.WebhookEventType -- the one place notification copy
is generated from an event's payload, keeping app.notifications.service
free of per-event-type string formatting.

Phase 25: every string here comes from app.localization's `t(language,
key)` -- there is no hardcoded English left in this module. `language` is
resolved PER RECIPIENT by the caller (app.notifications.service.emit_event,
via app.localization.resolve_recipient_language) before this module is
ever called, so two different members of the same organization can each
receive this event's notification/email in their own language.

A `payload` here is always the exact same dict
app.services.webhook_events.record_webhook_event already received (a
Response-model dump captured at the domain mutation's own commit
boundary) -- this module only ever reads from it, never re-fetches or
re-derives anything from the database itself. Every renderer accesses
payload fields defensively (`.get`, with a translated fallback) because
the schema of a Response-model dump can, in principle, evolve
independently of this module.

Adding a new WebhookEventType does not require a renderer here: an event
type with no entry falls back to a generic, still-translated title/body
(see render_notification_copy) rather than raising -- but adding one is
recommended so notifications read naturally.
"""

from collections.abc import Callable

from app.localization import t
from app.webhook_event_type import WebhookEventType

_Renderer = Callable[[dict, str], tuple[str, str]]


def _customer_label(payload: dict, language: str) -> str:
    return payload.get("name") or t(language, "notif_default_customer_label")


def _quote_label(payload: dict, language: str) -> str:
    return payload.get("quote_number") or t(language, "notif_default_quote_label")


def _invoice_label(payload: dict, language: str) -> str:
    return payload.get("invoice_number") or t(language, "notif_default_invoice_label")


def _product_label(payload: dict, language: str) -> str:
    return payload.get("name") or t(language, "notif_default_product_label")


def _customer_created(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_customer_created_title"),
        t(language, "notif_customer_created_body").format(name=_customer_label(payload, language)),
    )


def _customer_updated(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_customer_updated_title"),
        t(language, "notif_customer_updated_body").format(name=_customer_label(payload, language)),
    )


def _customer_deleted(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_customer_deleted_title"),
        t(language, "notif_customer_deleted_body").format(name=_customer_label(payload, language)),
    )


def _product_created(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_product_created_title"),
        t(language, "notif_product_created_body").format(name=_product_label(payload, language)),
    )


def _product_updated(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_product_updated_title"),
        t(language, "notif_product_updated_body").format(name=_product_label(payload, language)),
    )


def _product_archived(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_product_archived_title"),
        t(language, "notif_product_archived_body").format(name=_product_label(payload, language)),
    )


def _product_restored(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_product_restored_title"),
        t(language, "notif_product_restored_body").format(name=_product_label(payload, language)),
    )


def _quote_created(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_quote_created_title"),
        t(language, "notif_quote_created_body").format(quote_number=_quote_label(payload, language)),
    )


def _quote_updated(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_quote_updated_title"),
        t(language, "notif_quote_updated_body").format(quote_number=_quote_label(payload, language)),
    )


def _quote_deleted(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_quote_deleted_title"),
        t(language, "notif_quote_deleted_body").format(quote_number=_quote_label(payload, language)),
    )


def _quote_sent(payload: dict, language: str) -> tuple[str, str]:
    customer = payload.get("customer_name") or t(language, "notif_default_customer_reference")
    return (
        t(language, "notif_quote_sent_title"),
        t(language, "notif_quote_sent_body").format(quote_number=_quote_label(payload, language), customer=customer),
    )


def _quote_accepted(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_quote_accepted_title"),
        t(language, "notif_quote_accepted_body").format(quote_number=_quote_label(payload, language)),
    )


def _quote_rejected(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_quote_rejected_title"),
        t(language, "notif_quote_rejected_body").format(quote_number=_quote_label(payload, language)),
    )


def _quote_converted(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_quote_converted_title"),
        t(language, "notif_quote_converted_body").format(quote_number=_quote_label(payload, language)),
    )


def _invoice_created(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_invoice_created_title"),
        t(language, "notif_invoice_created_body").format(invoice_number=_invoice_label(payload, language)),
    )


def _invoice_updated(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_invoice_updated_title"),
        t(language, "notif_invoice_updated_body").format(invoice_number=_invoice_label(payload, language)),
    )


def _invoice_sent(payload: dict, language: str) -> tuple[str, str]:
    customer = payload.get("customer_name") or t(language, "notif_default_customer_reference")
    return (
        t(language, "notif_invoice_sent_title"),
        t(language, "notif_invoice_sent_body").format(invoice_number=_invoice_label(payload, language), customer=customer),
    )


def _organization_plan_changed(payload: dict, language: str) -> tuple[str, str]:
    new_plan = payload.get("new_plan") or {}
    plan_label = new_plan.get("code") or t(language, "notif_default_plan_label")
    return (
        t(language, "notif_organization_plan_changed_title"),
        t(language, "notif_organization_plan_changed_body").format(plan_label=plan_label),
    )


def _financial_insight_requested(payload: dict, language: str) -> tuple[str, str]:
    return t(language, "notif_financial_insight_requested_title"), t(
        language, "notif_financial_insight_requested_body"
    )


def _financial_insight_generated(payload: dict, language: str) -> tuple[str, str]:
    return t(language, "notif_financial_insight_generated_title"), t(
        language, "notif_financial_insight_generated_body"
    )


def _financial_insight_failed(payload: dict, language: str) -> tuple[str, str]:
    return t(language, "notif_financial_insight_failed_title"), t(language, "notif_financial_insight_failed_body")



def _note_label(payload: dict, language: str) -> str:
    """The note's own formatted number ("CN-000004"), which the emitter
    already put in the payload -- never re-derived here, so the
    notification and the document can never disagree."""
    return payload.get("note_number") or payload.get("note_id", "")


def _note_kind(payload: dict, language: str) -> str:
    key = (
        "notif_credit_note_kind"
        if payload.get("note_type") == "credit"
        else "notif_debit_note_kind"
    )
    return t(language, key)


def _adjustment_note_created(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_adjustment_note_created_title").format(
            kind=_note_kind(payload, language)
        ),
        t(language, "notif_adjustment_note_created_body").format(
            note_number=_note_label(payload, language)
        ),
    )


def _adjustment_note_issued(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_adjustment_note_issued_title").format(
            kind=_note_kind(payload, language)
        ),
        t(language, "notif_adjustment_note_issued_body").format(
            note_number=_note_label(payload, language),
            total=payload.get("total", ""),
            currency=payload.get("currency_code", ""),
        ),
    )


def _adjustment_note_voided(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_adjustment_note_voided_title").format(
            kind=_note_kind(payload, language)
        ),
        t(language, "notif_adjustment_note_voided_body").format(
            note_number=_note_label(payload, language)
        ),
    )


def _adjustment_note_sent(payload: dict, language: str) -> tuple[str, str]:
    return (
        t(language, "notif_adjustment_note_sent_title").format(
            kind=_note_kind(payload, language)
        ),
        t(language, "notif_adjustment_note_sent_body").format(
            note_number=_note_label(payload, language)
        ),
    )

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
    WebhookEventType.adjustment_note_created: _adjustment_note_created,
    WebhookEventType.adjustment_note_issued: _adjustment_note_issued,
    WebhookEventType.adjustment_note_voided: _adjustment_note_voided,
    WebhookEventType.adjustment_note_sent: _adjustment_note_sent,
    WebhookEventType.organization_plan_changed: _organization_plan_changed,
    WebhookEventType.financial_insight_requested: _financial_insight_requested,
    WebhookEventType.financial_insight_generated: _financial_insight_generated,
    WebhookEventType.financial_insight_failed: _financial_insight_failed,
}


def render_notification_copy(event_type: WebhookEventType, payload: dict, language: str) -> tuple[str, str]:
    renderer = _RENDERERS.get(event_type)
    if renderer is None:
        return event_type.value, t(language, "notif_generic_fallback_body")
    return renderer(payload, language)
