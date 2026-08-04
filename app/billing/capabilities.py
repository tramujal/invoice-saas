"""The reusable capability layer Phase 17A builds -- pure composition
over app.services.entitlements (what a plan allows) and
app.services.organization_usage (how much is currently used). Neither of
those two modules is duplicated here: this file computes nothing about a
plan's limits or an organization's live counts itself, it only combines
numbers those two already compute correctly.

Every function here answers one of two question shapes: "can this
organization do X right now" (a bool) or "how many more of X can it
create right now" (an int, or None for unlimited -- the same convention
app.services.entitlements.get_limit already establishes).

Phase 17B wires this module into every real enforcement point:
- app.services.plan_limits (the row-locking, 409-raising layer used by
  every creation router) now sources its own limit/used numbers from
  OrganizationCapabilities below instead of recomputing them a second
  time -- this module's remaining_* functions are the single source of
  truth for every quota, plan_limits.py just adds the atomic
  check-and-raise ceremony on top.
- app.billing.enforcement wraps the boolean can_use_* checks here into
  raising helpers for feature-flagged (not quota-based) capabilities
  (AI, analytics).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.entitlements import Entitlements, get_organization_entitlements
from app.services.organization_usage import (
    count_ai_actions_current_month,
    count_api_keys,
    count_customers,
    count_invoices_current_month,
    count_products,
    count_quotes_current_month,
    count_users,
    count_webhooks,
    count_whatsapp_actions_current_month,
    count_whatsapp_users,
)


@dataclass(frozen=True)
class OrganizationCapabilities:
    """A resolved, point-in-time snapshot of what one organization can do
    right now -- its entitlements (from its plan, via its Subscription)
    plus live usage counts, bundled together so a caller doesn't have to
    fetch both separately for every question. A plain snapshot, not a
    live view: like Entitlements itself, it can go stale the instant
    after it's read, which is fine for the read-only display/decision
    use cases this module serves."""

    entitlements: Entitlements
    usage_users: int
    usage_customers: int
    usage_products: int
    usage_invoices: int
    usage_quotes: int
    usage_ai_actions: int
    usage_api_keys: int
    usage_webhooks: int
    # Phase 23 additions -- see app.services.organization_usage's
    # count_whatsapp_users/count_whatsapp_actions_current_month for what
    # each actually counts.
    usage_whatsapp_users: int
    usage_whatsapp_actions: int


def get_organization_capabilities(db: Session, organization_id: str) -> OrganizationCapabilities:
    """The one function every capability check in this module starts
    from -- resolves entitlements once and every live count once, so a
    caller checking several capabilities in a row (e.g. rendering a full
    "what can I do" panel) never re-queries the same numbers per
    question."""
    entitlements = get_organization_entitlements(db, organization_id)
    return OrganizationCapabilities(
        entitlements=entitlements,
        usage_users=count_users(db, organization_id),
        usage_customers=count_customers(db, organization_id),
        usage_products=count_products(db, organization_id),
        usage_invoices=count_invoices_current_month(db, organization_id),
        usage_quotes=count_quotes_current_month(db, organization_id),
        usage_ai_actions=count_ai_actions_current_month(db, organization_id),
        usage_api_keys=count_api_keys(db, organization_id),
        usage_webhooks=count_webhooks(db, organization_id),
        usage_whatsapp_users=count_whatsapp_users(db, organization_id),
        usage_whatsapp_actions=count_whatsapp_actions_current_month(db, organization_id),
    )


def _remaining(limit: int | None, used: int) -> int | None:
    """None means unlimited (matches get_limit's own convention);
    otherwise never negative, even if usage has somehow crept past the
    limit (e.g. a plan downgrade after the fact)."""
    if limit is None:
        return None
    return max(0, limit - used)


# --- feature capabilities ------------------------------------------------


def can_use_ai(caps: OrganizationCapabilities) -> bool:
    return caps.entitlements.ai_enabled


def can_use_analytics(caps: OrganizationCapabilities) -> bool:
    return caps.entitlements.analytics_enabled


def can_use_forecasting(caps: OrganizationCapabilities) -> bool:
    return caps.entitlements.forecasting_enabled


def can_use_background_jobs(caps: OrganizationCapabilities) -> bool:
    return caps.entitlements.background_jobs_enabled


def can_use_whatsapp(caps: OrganizationCapabilities) -> bool:
    """Phase 23 -- the experimental WhatsApp assistant's all-or-nothing
    feature flag. Deliberately separate from can_use_whatsapp_voice_messages
    below: a plan can allow text commands without allowing voice notes."""
    return caps.entitlements.whatsapp_enabled


def can_use_whatsapp_voice_messages(caps: OrganizationCapabilities) -> bool:
    return caps.entitlements.voice_messages_enabled


# --- remaining quotas -----------------------------------------------------


def remaining_invoice_quota(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.max_invoices_per_month, caps.usage_invoices)


def remaining_quote_quota(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.max_quotes_per_month, caps.usage_quotes)


def remaining_users(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.max_users, caps.usage_users)


def remaining_customers(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.max_customers, caps.usage_customers)


def remaining_products(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.max_products, caps.usage_products)


def remaining_ai_actions_quota(caps: OrganizationCapabilities) -> int | None:
    """The monthly AI-action *quota* -- distinct from can_use_ai below,
    which is the all-or-nothing feature flag. A plan can have ai_enabled
    but still cap how many AI actions it allows per month (see
    app.services.plan_limits.LimitedResource.ai_actions, the pre-Phase
    17A quota this mirrors)."""
    return _remaining(caps.entitlements.max_ai_actions_per_month, caps.usage_ai_actions)


def remaining_api_keys(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.max_api_keys, caps.usage_api_keys)


def remaining_webhooks(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.max_webhooks, caps.usage_webhooks)


def remaining_whatsapp_users(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.max_whatsapp_users, caps.usage_whatsapp_users)


def remaining_whatsapp_actions_quota(caps: OrganizationCapabilities) -> int | None:
    return _remaining(caps.entitlements.monthly_whatsapp_actions, caps.usage_whatsapp_actions)


# --- creation capabilities (derived from the quotas above) -----------------


def can_create_invoice(caps: OrganizationCapabilities) -> bool:
    remaining = remaining_invoice_quota(caps)
    return remaining is None or remaining > 0


def can_create_quote(caps: OrganizationCapabilities) -> bool:
    remaining = remaining_quote_quota(caps)
    return remaining is None or remaining > 0


def can_create_customer(caps: OrganizationCapabilities) -> bool:
    remaining = remaining_customers(caps)
    return remaining is None or remaining > 0


def can_create_product(caps: OrganizationCapabilities) -> bool:
    remaining = remaining_products(caps)
    return remaining is None or remaining > 0


def can_create_api_key(caps: OrganizationCapabilities) -> bool:
    remaining = remaining_api_keys(caps)
    return remaining is None or remaining > 0


def can_create_webhook(caps: OrganizationCapabilities) -> bool:
    remaining = remaining_webhooks(caps)
    return remaining is None or remaining > 0


def can_link_whatsapp_user(caps: OrganizationCapabilities) -> bool:
    remaining = remaining_whatsapp_users(caps)
    return remaining is None or remaining > 0
