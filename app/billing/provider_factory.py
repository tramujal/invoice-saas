"""Resolves the configured BillingProvider. Mirrors app/ai/factory.py's
get_ai_provider()/is_ai_configured() pattern exactly, adapted for a
service that (unlike AI) is constructed once per BillingService instance
rather than called fresh inside every route body.

This is the ONE place in the app that imports a concrete provider class
(StripeProvider today; a future Mercado Pago/Paddle/LemonSqueezy provider
tomorrow) -- app.billing.service.BillingService, every router, and every
job import only BillingProvider (app.billing.provider_base) and this
factory, never a concrete provider module directly. Each concrete
provider module is imported lazily, inside the branch that selects it, so
selecting "none" (the default) never even touches a concrete provider's
own imports (e.g. `requests`, already a dependency here, but a future
provider could need one this app doesn't otherwise require).
"""

import logging
import os

from app.billing.null_provider import NullBillingProvider
from app.billing.provider_base import BillingProvider, BillingProviderNotConfiguredError

logger = logging.getLogger(__name__)

# Unset (or "none") BILLING_PROVIDER keeps behaving exactly as every phase
# before this one: BillingService(db) with no provider argument, backed by
# NullBillingProvider, which is what "the app doesn't try to charge
# anyone" without a real provider configured actually looks like.
_DEFAULT_PROVIDER = "none"

# Which env vars each supported provider requires, purely for the cheap
# is_billing_provider_configured() check below -- the concrete provider's
# own constructor is still the single source of truth for what it
# actually needs (see StripeProvider.from_env).
_REQUIRED_ENV_VARS: dict[str, tuple[str, ...]] = {
    "stripe": ("STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET"),
}


def is_billing_provider_configured() -> bool:
    """Cheap check for whether get_billing_provider() would currently
    return a provider capable of real provider calls (as opposed to
    NullBillingProvider) -- no provider object is constructed. Mirrors
    app.ai.factory.is_ai_configured()'s own role: a status page or admin
    UI can show "payment provider: configured/not configured" without
    paying the cost (or risk) of actually instantiating one."""
    provider_name = (os.environ.get("BILLING_PROVIDER") or _DEFAULT_PROVIDER).strip().lower()
    if provider_name == _DEFAULT_PROVIDER:
        return False
    required = _REQUIRED_ENV_VARS.get(provider_name)
    if required is None:
        return False
    return all(os.environ.get(var) for var in required)


def get_billing_provider() -> BillingProvider:
    """Resolves the configured BillingProvider from BILLING_PROVIDER.

    Called explicitly wherever a provider-backed BillingService is
    needed (`BillingService(db, provider=get_billing_provider())`) --
    like get_ai_provider()/get_email_sender(), not as a bare FastAPI
    Depends() parameter on BillingService itself, since BillingService is
    constructed directly throughout the app (routers, jobs, the CLI
    bootstrap script), not exclusively inside request handlers. Routers
    that need a request-scoped, HTTP-error-mapped version of this same
    resolution use app.deps.get_billing_provider_dependency instead,
    which wraps this function and translates
    BillingProviderNotConfiguredError into a clean 503.

    Unset or "none" returns NullBillingProvider() -- always succeeds,
    never raises; this is the fully valid default state every existing
    call site already relies on. Only an EXPLICITLY selected provider
    (e.g. BILLING_PROVIDER=stripe) that is then missing its own required
    configuration raises BillingProviderNotConfiguredError -- "you asked
    for a provider and it isn't ready" is an error; "you didn't ask for
    one" is not.
    """
    provider_name = (os.environ.get("BILLING_PROVIDER") or _DEFAULT_PROVIDER).strip().lower()

    if provider_name == _DEFAULT_PROVIDER:
        return NullBillingProvider()

    if provider_name == "stripe":
        # Lazy import -- selecting "stripe" is the only path that ever
        # touches app.billing.stripe_provider, keeping every other call
        # site free of even an indirect dependency on Stripe's own
        # request/response shapes.
        from app.billing.stripe_provider import StripeProvider

        logger.info("get_billing_provider: resolving provider=stripe")
        return StripeProvider.from_env()

    logger.error(
        "get_billing_provider: unknown BILLING_PROVIDER=%r (expected one of: none, stripe)",
        provider_name,
    )
    raise BillingProviderNotConfiguredError(
        f"Unknown BILLING_PROVIDER {provider_name!r}. Expected 'none' or 'stripe'."
    )
