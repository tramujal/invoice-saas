# Screenshots

The complete shot list for this project's README, portfolio writeup, and
any future landing page — every image referenced anywhere in the docs,
plus a few recommended extras, in one place. **No images are generated
by this document** — it's a checklist for capturing them.

Capture at the specified viewport using the browser's own device
emulation (or a real device for the mobile shots — emulation is fine for
everything else). Use the account/data set up per
[`docs/demo.md`](demo.md) so every shot shows realistic, non-empty data.
Save as PNG, into `docs/screenshots/`, using the exact filename listed
(these are the paths already referenced from `README.md`).

| File | Page | Viewport | Purpose |
| --- | --- | --- | --- |
| `dashboard-overview.png` | `/dashboard` | 1440×900 (desktop) | The README's hero image — KPI cards, revenue chart, and at least one AI-narrated insight visible. This is the single image most people will see first; make it count. |
| `invoices-list.png` | `/invoices` | 1440×900 | The invoice table with a mix of paid/pending/overdue statuses visible, plus the filter toolbar. |
| `quotes-list.png` | `/quotes` | 1440×900 | The quote table showing several lifecycle statuses (draft, sent, accepted, expired) at once — the whole point is visually proving the lifecycle exists. |
| `public-quote-page.png` | `/quotes/public/{token}` (open in a private window, **not logged in**) | 1024×768 or mobile — whichever renders cleaner | The no-login customer-facing accept/reject page. Capture *before* clicking accept/reject, with both buttons visible. |
| `team-permissions.png` | `/settings/team` | 1440×900 | The member list with at least two different roles visible (e.g. owner + member), and ideally the role-change dropdown open to show the constrained options. |
| `whatsapp-share.png` | An invoice or quote detail view, with the "Open in WhatsApp" action visible (button, or the prefilled WhatsApp Web compose window it opens) | 1440×900 | Proves the share action exists and what it actually prefills — don't send anything for the shot. |
| `dashboard-mobile.png` | `/dashboard` | 390×844 (iPhone 12/13/14 class) | The dashboard rendering cleanly at a real mobile width — the counter-image to `dashboard-overview.png`. |
| `ai-assistant-propose-confirm.png` | `/assistant`, mid-conversation | 1440×900 | The moment an action proposal is shown (e.g. "Create invoice for..."), with the Confirm/Cancel buttons visible and *not yet clicked* — this is the shot that proves actions are proposed, not auto-executed. |

## Recommended additional screenshots

Not currently referenced from the README, but worth having for a fuller
portfolio page or case study.

| File | Page | Viewport | Purpose |
| --- | --- | --- | --- |
| `settings-webhooks.png` | `/settings/webhooks` | 1440×900 | The endpoint list plus the event-subscription create form — shows the webhooks feature is a real, configurable integration surface, not just a checkbox. |
| `settings-webhooks-secret.png` | `/settings/webhooks`, secret-reveal dialog open | 1440×900 | The "shown exactly once" signing-secret dialog — a good talking point for the security section of a portfolio writeup. |
| `settings-api-keys.png` | `/settings/api-keys` | 1440×900 | The API key list with scoped permissions visible per key. |
| `settings-audit-log.png` | `/settings/audit-log`, with a details drawer open | 1440×900 | The tenant audit timeline with an entry's metadata expanded — shows the event pipeline's output, not just its existence. |
| `settings-notifications.png` | `/settings/notifications` | 1440×900 | The in-app inbox with a few unread notifications. |
| `settings-plan-limits.png` | `/settings/plan` | 1440×900 | Usage-vs-limit bars for at least one near-limit resource, to show enforcement isn't just a pricing table. |
| `public-api-docs.png` | `/docs` (FastAPI's own Swagger UI) | 1440×900 | The auto-generated OpenAPI docs for `/api/v1/...` — a fast way to prove a real public API exists. |
| `admin-organizations.png` | `/admin/organizations` | 1440×900 | The platform-admin organization list — proves the operator console is a distinct, populated surface. |
| `admin-organization-detail.png` | `/admin/organizations/{id}` | 1440×900 | Usage bars, plan, and the suspend/reactivate action — the platform operator's view of one tenant. |
| `admin-jobs.png` | `/admin/jobs` | 1440×900 | The background-job queue with a mix of statuses (pending/succeeded/failed) — visual proof the durable queue is a real, observable system, not an implementation detail. |
| `admin-audit-log.png` | `/admin/audit-log`, with a details drawer open | 1440×900 | The platform-level audit log, showing a suspend/plan-change/role-grant action with its mandatory reason. |
| `admin-subscriptions.png` | `/admin/subscriptions` | 1440×900 | The subscription list across organizations — pairs well with the billing/Stripe section of the architecture doc. |
| `mobile-settings-nav.png` | `/settings/webhooks` (or any Settings page) | 375×812 | The horizontally-scrollable Settings tab strip at a narrow width — the concrete "before" this UX pass fixed, useful for a portfolio case study on the mobile-responsiveness work. |
| `mobile-row-actions-menu.png` | Any list page (e.g. `/invoices`), row-actions menu open | 390×844 | The portal-based row-actions dropdown, correctly positioned and fully reachable at a mobile width. |
| `landing-page.png` | `/` (marketing/landing page, logged out) | 1440×900 | First impression for anyone who hasn't registered yet. |
| `architecture-diagram.png` | N/A — export of the Mermaid diagram in `docs/architecture.md`'s [System architecture](architecture.md#system-architecture) section | N/A | A rendered (not hand-drawn) architecture diagram is one of the highest-value single images for a portfolio README. Most Markdown renderers (GitHub included) render the Mermaid block directly — this PNG is only needed for platforms that don't (e.g. pasting into a slide deck or a non-Markdown portfolio site). |

## Capture checklist

- [ ] Use the [demo setup](demo.md#demo-organization--user) so every
      shot shows realistic data — no empty states except where an empty
      state genuinely *is* the point (e.g. don't fake it, but don't lead
      with it either).
- [ ] Keep browser chrome out of the shot (use device-emulation
      screenshot tools, not a raw OS screenshot with the address bar
      visible) — or crop it out afterward.
- [ ] Redact anything that looks like a real secret even though it's
      demo data (API keys, webhook signing secrets) — capture the
      "revealed" UI state with a clearly fake-looking value, not
      something that merely *isn't* a real credential but still looks
      like one at a glance.
- [ ] Match light/dark mode consistently across the set if the app
      supports both — don't mix.
- [ ] Re-export `dashboard-overview.png` and `dashboard-mobile.png` last,
      after everything else looks right — they're the two images most
      likely to actually get seen.
