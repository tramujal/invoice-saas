# Event-driven notification architecture (Phase 20)

## Governance (frozen as of Phase 20 approval)

`app.notifications.service.emit_event` is the **single, frozen entry
point** for every domain event this platform raises. This is a standing
architectural rule, not just this phase's implementation choice:

- **No parallel notification mechanisms.** A future integration never
  gets its own bespoke "fire an event" path alongside `emit_event` —
  there is exactly one place a domain event is raised, exactly like
  there is exactly one place a webhook event was raised before this
  phase.
- **Every future channel subscribes to the existing pipeline.** Slack,
  Discord, SMS, Push, an audit-log consumer, an analytics sink — each
  of these is a new *subscriber* added inside (or alongside)
  `emit_event`'s own fan-out, or a new consumer of the `WebhookEvent`
  table it already writes. None of them are ever wired to call
  `app.services.customers`, `app.services.invoices`, `app.services.quotes`,
  etc. directly to "also notify X" — that would be exactly the
  duplicated-business-logic problem Phase 20 was built to avoid.
- **`WebhookEventType` is the canonical event catalog.** Its members are
  the platform's entire vocabulary of "things that happened," consumed
  by every channel. A new event type is still added in exactly the two
  steps its own docstring describes (add the member, add the one
  `emit_event` call at the real transaction boundary) — never a
  channel-specific enum, never a second catalog.

Concretely, adding a new channel means extending `emit_event`'s own body
(or adding a sibling function it also calls, in the same
`app/notifications/` or a clearly-related package) — never adding a
second call site elsewhere in the codebase that also reacts to a
business mutation.

## Why this exists

Phases 15B/15C already built a durable, transaction-safe event bus:
`app.services.webhook_events.record_webhook_event` writes one
`WebhookEvent` row (the immutable, point-in-time record of "this
happened") plus one pending `WebhookDelivery` per subscribed
`WebhookEndpoint`, in the SAME transaction as the business mutation that
caused it, and enqueues durable `webhook.deliver` `BackgroundJob` rows
(Phase 15C) for actual HTTP delivery. This was, in substance, already a
central event model — it just only ever drove one channel.

Phase 20 extends this to two more channels — in-app notifications and
notification emails — **without duplicating that event-emission logic**.
The webhook channel is untouched: same table, same function, same tests,
same plan-gating. What's new sits beside it, driven from the exact same
call.

## The central entry point

```
app/notifications/
├── service.py   -- emit_event(...), is_email_enabled/set_email_enabled
└── copy.py      -- render_notification_copy(event_type, payload) -> (title, body)
```

`app.notifications.service.emit_event` is the one new call every
business service function makes (replacing a direct call to
`record_webhook_event`). It takes the exact same five keyword arguments
(`organization_id`, `event_type`, `object_type`, `object_id`, `payload`)
`record_webhook_event` always took, and internally:

1. Calls `record_webhook_event(...)` **unchanged** — the webhook channel
   is a pure pass-through, byte-for-byte identical to Phase 15B/15C.
2. Renders a human title/body once (`app.notifications.copy
   .render_notification_copy`) from the same payload dict every webhook
   subscriber already receives.
3. Creates one `Notification` row (see `app.models.Notification`) for
   **every active member** of the organization, unconditionally — every
   member's in-app inbox always reflects what happened, with no opt-out.
4. Enqueues one `notification.email` `BackgroundJob` per active member
   who (a) hasn't opted out via `NotificationPreference.email_enabled`
   and (b) has a verified email address — mirroring this app's existing
   rule that no transactional email ever goes to an unconfirmed address.

`app.webhook_event_type.WebhookEventType` (renamed in spirit, not in
code, to avoid an unnecessary invasive rename — see its own updated
docstring) is now the shared event vocabulary for all three channels,
not webhooks alone. Adding a new event type is still exactly the two
steps its docstring describes (add the member, add the one `emit_event`
call at the real transaction boundary), plus an optional third step
(add a renderer to `copy.py` — an event type with none falls back to a
generic, still-readable title/body rather than raising).

## Why in-app is unconditional but email is opt-out-able

In-app notifications are a baseline platform capability, not a
premium feature or a per-user annoyance risk — every member always sees
what happened in their organization. Email is the channel with a real
cost to getting wrong (inbox spam), so `NotificationPreference` exists
purely to let a user opt out of *email* specifically; there is
deliberately no equivalent for the in-app channel.

`NotificationPreference` rows are created lazily, only when a user
actually changes the default away from `email_enabled=True` — mirroring
`ProviderCustomer`'s own lazy-row-creation precedent from the billing
domain. Absence of a row means the default, not `False`.

## Why the email job references a Notification row, not raw text

`app.jobs.handlers.notification.NotificationEmailPayload` carries only
`{"notification_id": "..."}` — never the rendered title/body directly —
exactly mirroring `WebhookDeliverPayload`'s own "only an id, the handler
re-fetches everything" convention. The `Notification` row IS the frozen,
point-in-time snapshot (same principle as `WebhookEvent.payload`): a
future change to `copy.py`'s templates can never retroactively alter an
already-delivered notification's text, because the handler never
re-renders anything — it only reads back what `emit_event` already wrote.

## Plan-gating: webhooks are gated, in-app/email are not

`record_webhook_event` already enforces
`app.billing.capabilities.can_use_background_jobs` for the webhook
channel (unchanged since Phase 17B). `emit_event` deliberately does
**not** apply that same gate to in-app/email — notifications are a core
platform capability every organization gets regardless of plan, unlike
outbound webhook delivery infrastructure, which remains the one
plan-gated channel. (`notification.email` IS still a `BackgroundJob`
row — the job queue itself has no plan awareness — it is simply never
skipped for a plan reason the way `webhook.deliver` enqueuing is.)

## The notification.email job

```
app/jobs/handlers/notification.py
├── NotificationEmailPayload { notification_id: str }
└── handle_notification_email(db, job, payload) -> JobResult
    ├── Notification row missing            -> permanently_failed
    ├── recipient missing/unverified         -> succeeded (skip, not an error)
    ├── get_email_sender() raises HTTPException (not configured/disabled)
    │                                         -> permanently_failed
    └── EmailSender.send() raises EmailSendError
                                              -> retry (bounded by max_attempts)
```

Registered exactly like `webhook.deliver`/`webhook.retry` (Phase 15C's
job registry): `app/job_type.py` gained one new `JobType
.notification_email = "notification.email"` member, and this handler
module calls `register_job(...)` at import time via
`app/jobs/handlers/__init__.py`.

## The tenant-facing API

`app/routers/notifications.py`, gated by `require_org_member` only (no
separate `Permission` — a member's own inbox/preferences are never a
privileged view of anyone else's data):

- `GET /organizations/{id}/notifications` — paginated (`limit`/`offset`),
  `unread_only` filter, scoped to `current_user`'s own rows.
- `POST /organizations/{id}/notifications/{notification_id}/read`
- `POST /organizations/{id}/notifications/read-all`
- `GET`/`PATCH /organizations/{id}/notification-preferences`

## Frontend

- `components/layout/NotificationBell.tsx` — unread-count badge +
  dropdown preview (latest 5), rendered in both `AppShell`'s desktop
  sidebar header and mobile top bar. Refetches when opened (not on a
  polling interval — this app has no near-real-time UI anywhere else
  either).
- `app/(dashboard)/settings/notifications/page.tsx` — full inbox
  (paginated), mark-read/mark-all-read, and the email-preference toggle.
  New `SettingsSubNav` tab alongside Organization/Team/Plan/API
  Keys/Webhooks.

## What BillingService still never touches

`BillingService` remains entirely independent of notification delivery,
exactly as it was independent of webhook delivery before this phase: the
one webhook event this app emits from the billing domain
(`organization.plan_changed`) is raised from
`app.routers.platform_admin` (the router, above `BillingService`), not
from inside the service itself — Phase 20 changes that one call site
from `record_webhook_event(...)` to `emit_event(...)`, a pure rename,
with zero new code inside `app.billing.*`.
