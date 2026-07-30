"""Phase 21 -- read-only, cross-organization aggregate metrics for the
Platform Operations Dashboard. See docs/platform_operations_dashboard.md
for the full architecture.

Every function in this package is a pure query against models that
already exist and are already the single source of truth for their own
domain (Subscription/Plan for billing, BackgroundJob for jobs,
WebhookDelivery for webhooks, Notification for notifications,
AssistantAction for AI usage, OrganizationApiKey for API keys,
OrganizationMember for org/user counts). Nothing here writes anything,
nothing here duplicates a business rule already enforced elsewhere
(BillingService, app.notifications.service.emit_event, etc. remain the
only writers of their own domains) -- this package only reads and
aggregates, mirroring the exact style of the cross-org helpers
app.routers.platform_admin already established (_count_new_since,
_count_by_org, and friends) rather than introducing a second way to
query the same tables.
"""
