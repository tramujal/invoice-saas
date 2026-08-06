# Notification & Email Localization (Phase 25)

## Status

Every in-app notification and every notification-driven email is now
rendered in the RECIPIENT's own resolved language — no hardcoded English
remains in `app.notifications.copy`. Email templates unrelated to the
notification system (password reset, verification, invitations,
reminders, quotes) were already fully localized before this phase via
`app.localization`'s existing `t(language, key)` system; this phase closes
the one real gap (in-app/email notification copy) and extends the
resolution chain with a personal, per-user language preference.

## Language resolution chain

`app.localization.resolve_recipient_language(user, organization)`:

```
User.language (personal preference, if set and supported)
  ↓ (falls through when NULL or unsupported)
Organization.language (the organization's own configured default)
  ↓ (falls through when unsupported/unset)
"en" (DEFAULT_LANGUAGE)
```

`User.language` is a new, nullable column — `NULL` for every account
that existed before this migration ran (and for any invited member who
never had an opportunity to set one), which resolves to byte-for-byte
the same behavior as before this phase: falling through to the
organization's language, exactly as every email template already did.
**No historical notification is ever rewritten** — this only affects
notifications generated from this point forward; a Notification row
already in the database keeps the title/body it was created with,
permanently.

### Where `User.language` gets set

- **Registration** (`POST /auth/register`) — the language the visitor had
  selected on the public form (`RegisterRequest.language`, previously
  used only to localize the one-off verification email and then
  discarded) is now also persisted as that user's own preference.
- **Google Sign-In, new account** (`create_google_user`) — seeded from
  Google's own `locale` ID-token claim when present and it matches a
  supported language (`en`/`es`); otherwise left `NULL` (falls through to
  the organization's language, same as any other account).
- **Nothing else sets it in this phase** — there is no personal
  "notification language" picker in Settings yet (see Limitations). An
  existing user's language stays `NULL` (falling through to their
  organization's language) until a future phase adds one.

## Notification audit (every category from this phase's own checklist)

| Category | Mechanism | Localized? |
| --- | --- | --- |
| Customer | `WebhookEventType.customer_created/updated/deleted` via `emit_event` | Yes — `app.notifications.copy` |
| Invoice | `invoice_created/updated/sent` | Yes |
| Quote | `quote_created/updated/deleted/sent/accepted/rejected/converted` | Yes |
| Product | `product_created/updated/archived/restored` | Yes |
| Billing | `organization_plan_changed` (the only billing-related notification event that exists) | Yes |
| Webhook | **No "webhook delivery failed" notification/email exists in this codebase** — webhook delivery failures are tracked on the `WebhookDelivery` row itself (status/error_message, visible in Settings → Webhooks), never emitted as a `Notification`/email. Documented here as an honest audit finding, not fabricated as a new feature this phase didn't ask to build. | N/A (doesn't exist) |
| WhatsApp | The experimental WhatsApp assistant's own reply text (`app.whatsapp.service`) — a **separate, synchronous reply channel**, not a `Notification`/email at all. Already localized via `app.localization.get_language(organization)` before this phase, unchanged here (org-level only; WhatsApp has no natural analog of "recipient" the way an org-wide notification fan-out does). | Yes (pre-existing, org-level) |
| Platform | Platform Admin console actions (`PlatformAuditLog`) are an internal operator tool, not a tenant-facing notification — never routed through `emit_event`, out of scope for recipient-language localization. | N/A (internal tool) |
| Financial Intelligence | `financial_insight_requested/generated/failed` (Phase 24.3) | Yes |
| Background Jobs | Background jobs have no notification of their own distinct from the specific business event they're processing (e.g. the `financial_insight.generate` job's outcome IS the `financial_insight.generated`/`failed` event above) | Covered via the specific event types above |
| AI | The AI Financial Advisor's own lifecycle notifications are exactly the `financial_insight_*` rows above — there is no other AI-driven notification in this app | Yes |

## Email localization audit

| Template | Localized before this phase? | Notes |
| --- | --- | --- |
| Password reset | Yes | `app.email.templates.build_password_reset_email` |
| Email verification | Yes | `app.email.templates.build_verification_email` |
| Invitation / invitation-accepted | Yes | `app.email.invitation_templates` |
| Invoice send / reminders | Yes | `app.email.templates`, `app.email.reminder_templates` |
| Quote send / expiry reminders | Yes | `app.email.quote_templates` |
| Billing | No dedicated billing email template exists in this codebase (subscription/plan-change events surface as the `organization_plan_changed` notification/email above, not a separate template) | N/A (uses the notification path) |
| Webhook failures | No such email exists (see the Webhook row above) | N/A (doesn't exist) |
| Financial reports / AI report ready | **New in this phase** — `financial_insight.generated`/`failed`'s `Notification.title`/`.body` (localized per `app.notifications.copy`) IS the exact text `app.jobs.handlers.notification.handle_notification_email` sends as the email subject/body. No separate email template was written — this app's own established convention is that a `Notification`'s stored title/body already **is** the email content; localizing the notification automatically and correctly localizes the email, with zero duplication. | Yes |

**No duplicated templates**: every email template (old and new) resolves
its copy through the same `app.localization.t(language, key)` lookup
table — there was never a second, parallel copy of any string to keep in
sync.

## How a notification becomes an email, per-recipient

`app.notifications.service.emit_event` (the single, frozen entry point
for every domain event — see that module's own governance note) now:

1. Batch-fetches every active member's `User` row (already needed for the
   existing email-verified check) plus the `Organization` row once.
2. For **each** member, resolves `language =
   resolve_recipient_language(user, organization)` and renders
   `render_notification_copy(event_type, payload, language)`
   **independently** — two members of the same organization can and do
   get different title/body text for the exact same event.
3. Stores each member's own rendered copy on their own `Notification`
   row.
4. The `notification.email` background job (unchanged) reads
   `Notification.title`/`.body` verbatim as the email subject/body — it
   never re-translates or re-derives anything, so it inherits the
   correct per-recipient language automatically.

## Testing

`tests/test_notification_localization.py` — the resolution chain (user
preference wins; falls through to org; falls through to platform
default; ignores an unsupported personal preference; handles a missing
user), every `WebhookEventType` renders correctly and *differently* in
both `en` and `es` (no stray unformatted `{placeholder}`, no silent
English fallback for Spanish), and the end-to-end case: two members of
one organization with different language preferences receive genuinely
different `Notification.title`/`.body` text for the same real event
(`create_customer_record`).

## Limitations

- No personal "notification language" picker exists in Settings yet —
  `User.language` can currently only be set at signup (password
  registration form, or inferred from a Google account's `locale`
  claim). An existing user cannot change their own preference without a
  future phase adding that control; until then they keep following their
  organization's language, exactly as before this phase.
- Only `en`/`es` are supported (`app.localization.SUPPORTED_LANGUAGES`,
  unchanged by this phase) — this phase adds resolution *logic*, not new
  translated languages.
