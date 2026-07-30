"""The audit-timeline subsystem (Phase 22) -- every function here is
read-only or a single-row insert, never a second source of business
logic. record_audit_entry (service.py) is called from exactly one place,
app.notifications.service.emit_event's own fan-out, as just another
consumer of the frozen event pipeline (see that module's docstring). No
domain service (BillingService, app.services.customers/products/quotes/
invoices, ...) ever imports from this package -- they call emit_event and
remain completely unaware that an audit trail is being written at all.

list_audit_entries (queries.py) is the one place AuditEntry rows are read
back out, filtered and paginated, for the tenant-facing GET
/organizations/{id}/audit-entries endpoint (app.routers.audit).
"""
