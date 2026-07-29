# Billing provider architecture (Phase 18)

## Why this exists

Phases 14–17 built a complete, provider-independent billing domain:
`Plan`, `Subscription`, `SubscriptionEvent`, `app.billing.service
.BillingService` (every lifecycle rule), `app.billing.capabilities`
(read-only entitlement checks), and `app.billing.enforcement` (feature
gates). None of it talks to a payment processor — there was nothing to
charge anyone, so there was nothing to integrate.

Phase 18 introduces the first real payment-provider integration, but
**not** by wiring Stripe's SDK directly into `BillingService`. Instead:

1. A small, provider-agnostic interface — `BillingProvider`
   (`app/billing/provider_base.py`) — describes everything a payment
   provider needs to do for this app, in this app's own vocabulary.
2. `BillingService` depends on that interface only, never on a concrete
   provider's SDK, HTTP client, or event-naming.
3. Stripe is the first concrete implementation
   (`app/billing/stripe_provider.py`), but it is not privileged — a
   Mercado Pago, Paddle, or LemonSqueezy provider is exactly as much
   work to add, and none of them ever touch `BillingService`'s own code.

This is the same shape this codebase already uses for AI
(`app/ai/base.py` + `app/ai/factory.py`, Anthropic/Gemini as
implementations) and email (`app/email/base.py` + `app/email/factory.py`,
Resend as the implementation) — Phase 18 applies that established
pattern to billing rather than inventing a new one.

## The contract

```
app/billing/provider_base.py
├── BillingProvider (ABC)
│   ├── create_customer(...)             -> ProviderCustomer
│   ├── create_checkout_session(...)      -> ProviderCheckoutSession
│   ├── cancel_subscription(...)          -> None
│   ├── reactivate_subscription(...)      -> None
│   ├── change_subscription_plan(...)     -> None
│   ├── retrieve_subscription(...)        -> ProviderSubscriptionState
│   └── parse_webhook_event(...)          -> ProviderWebhookEvent
├── value objects: ProviderCustomer, ProviderCheckoutSession,
│   ProviderSubscriptionState, ProviderWebhookEvent,
│   CheckoutSessionRequest
├── BillingProviderEventType (the normalized webhook vocabulary):
│   checkout_completed, subscription_updated, subscription_canceled,
│   payment_failed
└── exceptions: BillingProviderError, BillingProviderNotConfiguredError,
    BillingProviderRequestError, InvalidWebhookSignatureError
```

`BillingProviderEventType` is the one piece of vocabulary every concrete
provider must translate its own event names into. Stripe calls one event
`checkout.session.completed`; Mercado Pago and Paddle each have their own
name for the same concept. `StripeProvider.parse_webhook_event` is the
**only** place `"checkout.session.completed"` (Stripe's own string)
appears anywhere in this codebase — everything above that translation
only ever sees `BillingProviderEventType.checkout_completed`.

## How BillingService uses it

`BillingService` (`app/billing/service.py`) gained one new field:

```python
provider: BillingProvider = field(default_factory=NullBillingProvider)
```

Every method that existed before Phase 18 is completely unchanged —
pure database lifecycle transitions, zero provider awareness. Five new
methods make up the entire provider-facing surface:

| Method | Purpose |
|---|---|
| `get_subscription_by_provider_reference` | Look up a Subscription by `(provider_name, provider_reference)` — how an incoming webhook is routed to a row. |
| `attach_provider_subscription` | Link an *existing* Subscription (every organization already has one, from registration) to a provider-side subscription id. |
| `sync_period_from_provider` | Overwrite `current_period_start/end`/`cancel_at_period_end` with the provider's own values — distinct from `renew()`, which advances by this app's own fixed 30/365-day length for subscriptions with no provider driving real dates. |
| `mark_past_due` | Record a failed renewal payment. |
| `start_checkout` | Create a provider customer + hosted checkout session for a plan/billing-period change. Never mutates the Subscription itself. |
| `sync_from_webhook_event` | The single entry point every provider webhook drives Subscription state through — switches on `BillingProviderEventType` only, dispatching to the lifecycle methods above (and to `upgrade_plan`/`change_plan`/`activate_subscription`/`cancel_immediately` for the existing ones). |

## Dependency injection

`app/billing/provider_factory.py::get_billing_provider()` is the **one**
place in the app that imports a concrete provider class. Everything
else — `BillingService`, every router, every job — imports only
`BillingProvider` and this factory function.

```python
provider = get_billing_provider()          # reads BILLING_PROVIDER env var
service = BillingService(db, provider=provider)
```

- `BILLING_PROVIDER` unset (or `"none"`) → `NullBillingProvider()`. Every
  method raises `BillingProviderNotConfiguredError` if actually called —
  this is the default for every environment that hasn't configured a
  payment provider, and it's what every pre-Phase-18 test and call site
  (`BillingService(db)`, no `provider` argument) still gets, so nothing
  about the existing 800+ backend tests changed.
- `BILLING_PROVIDER=stripe` → `StripeProvider.from_env()`, reading
  `STRIPE_API_KEY` and `STRIPE_WEBHOOK_SECRET`. Missing either raises
  `BillingProviderNotConfiguredError` immediately (fail closed, never a
  silent no-op on a payment feature).

Routers that need a request-scoped, HTTP-error-mapped version of this
same resolution use `app.deps.get_billing_provider_dependency` (a
`Depends()`-compatible wrapper that turns
`BillingProviderNotConfiguredError` into a clean `503`), matching how
`app.deps` already wraps every other cross-cutting dependency (`get_db`,
`get_current_user`, etc.).

## Adding a new provider (Mercado Pago, Paddle, LemonSqueezy, …)

1. Write `app/billing/<name>_provider.py` implementing every
   `BillingProvider` method, translating that provider's own webhook
   event names into `BillingProviderEventType`.
2. Add one branch in `get_billing_provider()` for `BILLING_PROVIDER=<name>`.
3. Add a `POST /billing/webhooks/<name>` route in
   `app/routers/billing_webhooks.py` (mirrors the existing
   `/billing/webhooks/stripe` route almost exactly — different signature
   verification, same `BillingService.sync_from_webhook_event` call at
   the end).

Nothing in `app/billing/service.py`, `app/billing/capabilities.py`,
`app/billing/enforcement.py`, or any existing router changes.

## Webhook idempotency

`app.models.ProviderWebhookReceipt` (new in Phase 18, `(provider_name,
event_id)` unique) is written by `app/routers/billing_webhooks.py`
*before* calling `sync_from_webhook_event`. A redelivered event (every
provider's webhook contract assumes this can happen) is detected there
and skipped — the receiving router returns `200` without re-applying any
mutation. This is new infrastructure the provider layer owns; it is not
a change to `Subscription`/`Plan`/`SubscriptionEvent`, the Phase 17A/17B
billing foundations.

## Scope decisions and trade-offs (read before changing this)

- **No provider SDK dependency.** `StripeProvider` calls Stripe's REST
  API directly via `requests` (already a dependency), the same choice
  this codebase already made for `AnthropicProvider`/`GeminiProvider`
  (`app/ai/*_provider.py`) and `ResendEmailSender`
  (`app/email/resend_provider.py`) — "the only file in the app aware
  this provider exists," in `resend_provider.py`'s own words. Webhook
  signature verification is plain `hmac`/`hashlib`, the same technique
  `app/webhook_signing.py` already uses for this app's own *outgoing*
  webhooks (which were themselves modeled on Stripe's own scheme).
- **Plan-to-price-id mapping lives in environment variables**
  (`STRIPE_PRICE_ID__<PLAN_CODE>__<MONTHLY|YEARLY>`), not a new column on
  `Plan`. Adding `Plan.stripe_price_id_monthly`/`_yearly` would have been
  the more conventional choice, but the phase's own instruction was not
  to modify the billing foundations without a bug forcing it — this
  keeps `Plan`/`Subscription` completely untouched at the schema level
  (only `ProviderWebhookReceipt`, a new independent table, was added).
- **No provider-customer-id caching.** `start_checkout` creates a fresh
  Stripe customer on every call — there's no `provider_customer_id`
  column anywhere to cache one in (same schema-freeze reasoning above).
  Stripe deduplicates customers reasonably well by email in practice;
  an organization that starts checkout more than once without completing
  it will accumulate more than one Stripe customer record. A future
  phase could add that column if this becomes an operational problem.
- **Backend only.** This phase does not add a frontend "Upgrade" button
  or checkout UI — matches every prior billing phase's explicit
  "no payment UI" scope note, and the checkout/webhook endpoints exist to
  prove the provider abstraction and Stripe adapter actually work
  end-to-end, not to ship a user-facing purchase flow yet.
