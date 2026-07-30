# Audit Timeline (Phase 22)

## Governance

This phase does not touch the event-pipeline freeze. `app.notifications.service.emit_event` remains the sole entry point for every domain event (see [docs/notifications.md](notifications.md)'s Governance section). The audit subsystem is exactly what that freeze anticipated: a fourth consumer added *inside* `emit_event`'s own fan-out, alongside the webhook, in-app notification, and email channels — never a second call site that reacts to a business mutation directly.

## What it is

A tenant-facing, append-only record of ordinary business-domain events — customer/product/quote/invoice lifecycle transitions — one row per `emit_event` call, scoped to a single organization and queryable by that organization's own admins/owner.

**Deliberately distinct from two existing, similarly-named tables:**
- `PlatformAuditLog` — platform-ADMIN actions on organizations/users (suspend, role changes, plan changes triggered by platform staff). A different, cross-tenant, privileged surface.
- `WebhookAuditLog` — webhook-ENDPOINT configuration actions (create/rotate-secret/disable). A narrow configuration trail, not business events.

`AuditEntry` is neither of those — it's the record of what actually happened to a business object, and who (if anyone) did it.

## Architecture

- **Model**: `app.models.AuditEntry` — `organization_id`, `actor_user_id` (nullable, ON DELETE SET NULL), `event_type` (reuses `WebhookEventType`'s string values verbatim — the single canonical event catalog), `resource_type`, `resource_id`, `metadata_json` (JSON-encoded snapshot, same payload the webhook channel already builds), `created_at`. Never updated or deleted by any code path.
- **Write path**: `app.audit.service.record_audit_entry` — called from exactly one place, inside `emit_event`'s own fan-out. No domain service (`app.services.customers`/`products`/`quotes`/`invoices`, `BillingService`, ...) imports from `app.audit` at all; they call `emit_event` and remain completely unaware an audit trail exists.
- **Read path**: `app.audit.queries.list_audit_entries` — filtered (actor, event type, resource type, resource id, date range) and paginated, backing the one endpoint below.
- **API**: `GET /organizations/{organization_id}/audit-entries`, gated by the new `Permission.audit_view` (granted to admin+owner, mirroring `settings.manage`'s sensitivity — an audit trail can reveal who changed/deleted what).

## The actor problem, and how it was solved

`emit_event` previously had no notion of "who." Recording a real actor required threading an optional `actor_user_id: str | None = None` parameter through `emit_event` and every one of its ~20 call sites (4 domain services, 2 CSV import modules, 1 platform-admin router call), plus every router/AI-tool caller that has a real user in scope. Sites with no human actor — a public/anonymous quote accept, an API-key-authenticated mutation, a system-triggered event — correctly pass `None`, never a fabricated system-user id.

## Verification

- Backend: 936/936 passing (920 prior + 16 new), zero regressions.
- Frontend: `tsc --noEmit` clean, full `vitest` suite green (271/271), `npm run build` succeeds (`/settings/audit-log`: 7.19 kB).
- Live browser verification: see the Phase 22 completion report.
