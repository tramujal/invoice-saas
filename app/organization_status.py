from enum import Enum


class OrganizationStatus(str, Enum):
    active = "active"
    # Set only via POST /admin/organizations/{id}/suspend (platform.
    # organizations.manage) -- blocks every org-scoped endpoint for this
    # organization's members (see app.deps._ensure_organization_active),
    # skips it in both scheduled reminder jobs, and blocks public quote
    # accept/reject and invitation acceptance for it. Never a soft-delete:
    # memberships, invoices, quotes, and customers are untouched.
    suspended = "suspended"
