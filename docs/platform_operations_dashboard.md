# Platform Operations Dashboard

## Governance (frozen as of Phase 20 approval)

This phase does not touch the notification/event pipeline. `app.notifications.service.emit_event` remains the sole entry point for domain events — see [docs/notifications.md](notifications.md)'s own Governance section. Nothing in this doc introduces a parallel notification mechanism; the dashboard only *reads* existing tables.

## Why this exists

Phase 21 turns the app's admin surface from "isolated feature pages" into a single owner-only operations dashboard, styled after what a production SaaS operator actually watches day to day: business health, usage, system health, and growth. It is built entirely on top of existing domain tables and existing services — no new business logic, no parallel queries, no fabricated numbers.

## Where it lives

- Backend: `app/platform_metrics/` (business.py, usage.py, growth.py, health.py) + 3 new endpoints on the existing `app/routers/platform_admin.py` router, plus an extension of the existing `_system_health()`.
- Frontend: `frontend/app/(admin)/admin/page.tsx` (rebuilt), 5 new presentational chart components under `frontend/components/admin/`.
- Both are gated by the existing `PlatformPermission.dashboard_view` — no new permission was introduced.

## Single source of truth per metric

| Section | Metric | Source |
|---|---|---|
| Business | Organizations | `Organization` count |
| Business | Active users | Distinct `OrganizationMember.user_id` where status=active |
| Business | Paying / Trial organizations | `Subscription.status` × `Plan.code != free` |
| Business | MRR / ARR | `Plan.monthly_price` / `yearly_price`, normalized to monthly via `Subscription.billing_period`; ARR = MRR × 12, never summed independently |
| Business | Churn rate (30d) | `SubscriptionEvent` cancel/expire events ÷ (paying now + churned), documented approximation — no daily snapshot table exists |
| Business | Conversion rate (30d) | `SubscriptionEvent` activated ÷ trial_started counts |
| Business | ARPU | MRR ÷ paying organizations |
| Usage | AI requests (30d) | `AssistantAction` (status=executed) |
| Usage | API key usage | `OrganizationApiKey` — active-key count (mirrors `api_key_status.get_effective_api_key_status`) + used-in-7d by `last_used_at`. **No per-request volume exists in the schema — deliberately not fabricated.** |
| Usage | Webhook deliveries | `WebhookDelivery` |
| Usage | Background jobs | `BackgroundJob` |
| Usage | Emails sent | `BackgroundJob` where job_type=notification.email, succeeded |
| Usage | Notifications created | `Notification` |
| System Health | Queue status / failed / retry | `BackgroundJob.status`, grouped (reuses Phase 15C's `JobStatus` vocabulary) |
| System Health | Storage usage | Always `0` — mirrors `organization_usage.count_storage`'s exact reasoning: no upload subsystem exists |
| System Health | Database size | New dialect-aware introspection (`pg_database_size` / `PRAGMA page_count`), returns `null` (not `0`) on failure |
| System Health | Avg API latency / error rate | New in-memory `app/request_metrics.py` middleware — a 15-minute rolling window, the only genuinely new runtime signal this phase adds, because no timing/error signal existed anywhere before |
| Growth | Daily signups | Earliest `OrganizationMember.created_at` per org (org creation-time proxy, same convention as existing `platform_admin.py` helpers) |
| Growth | Weekly active organizations | Orgs with an Invoice/Quote/Customer/Product created in the week |
| Growth | Monthly growth % | Org count now vs. 30 days ago |
| Growth | Feature adoption | `Plan` capability flags × paying `Subscription`s |

## Honesty gaps handled explicitly (not faked)

- **API request volume per key**: no counter exists in the schema. Reported instead: active-key count + 7-day-recency count.
- **Storage usage**: always `0`, matching the existing precedent for "no upload subsystem yet."
- **Database size**: `null` (not `0`) when introspection fails or the dialect is unsupported.
- **Churn rate**: explicitly an approximation (no historical daily snapshot table), documented in code and here rather than presented as exact.
- **API latency / error rate**: sourced from a new in-memory-only middleware; resets on process restart, which is acceptable for a live operational gauge (unlike durable delivery/job history) and is documented as such.

## Frontend behavior

The dashboard page fetches 5 independent resources in parallel (`useSectionLoader` hook, one call per section) so that one section's failure shows only that section's inline error banner — the other 4 keep rendering. Each section has its own loading skeleton (via `DashboardCard`'s `loading` prop and each chart's own skeleton block) and its own empty state (each chart component renders a translated "no data" message when its series is empty). Charts use the existing `recharts` styling convention already established by `RevenueTrendLineChart`/`TopServicesChart`.

## Testing

- Backend: `tests/platform_admin/test_operations_dashboard.py` — 25 tests covering MRR/ARR normalization, paying/trial classification, churn/conversion math, usage counts, queue grouping, database-size dialect branching, and permission enforcement on all 3 new endpoints.
- Frontend: `app/(admin)/admin/page.test.tsx` (loading, populated, per-section error isolation, empty states) plus one test file per new chart component (`OrganizationSplitChart`, `UsageOutcomeChart`, `DailySignupsChart`, `WeeklyActiveOrganizationsChart`, `FeatureAdoptionChart`) covering loading/empty/populated rendering.

## Verification

- Backend: full suite green (920+ tests, including the 25 new ones), zero regressions.
- Frontend: `npx tsc --noEmit` clean, full `vitest` suite green (one pre-existing, unrelated flaky test in `assistant/page.test.tsx` under parallel load — passes in isolation), `npm run build` succeeds (`/admin` route: 6.74 kB).
- Live browser verification: see the Phase 21 completion report.
