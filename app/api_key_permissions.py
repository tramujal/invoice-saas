"""Organization API key permission scopes.

A deliberately coarser, separate vocabulary from app.permissions.Permission
(the browser-session RBAC model) -- an API key's scopes describe what an
external integration may do to a *resource type*, not what a *role*
member may do inside the product UI. The two are intentionally decoupled:
changing what a Viewer can see in the browser must never change what an
integration key can read, and vice versa. Reusing Permission's own
(finer-grained: customer.read/write, invoice.read/create/edit/send, ...)
vocabulary here would force every external integration to understand
this app's internal role model instead of a small, stable public surface.

Same architectural pattern as app.permissions/app.platform_permissions
(str Enum + a pure membership check) -- deliberately no giant if/elif
chain, so a new permission is exactly one new enum member plus wiring it
into whatever router needs it, never a new branch in this module.
"""

from enum import Enum


class ApiKeyPermission(str, Enum):
    customers_read = "customers.read"
    customers_write = "customers.write"
    products_read = "products.read"
    products_write = "products.write"
    quotes_read = "quotes.read"
    quotes_write = "quotes.write"
    invoices_read = "invoices.read"
    invoices_write = "invoices.write"
    assistant_execute = "assistant.execute"


def has_api_key_permission(
    granted: frozenset[ApiKeyPermission], required: ApiKeyPermission
) -> bool:
    return required in granted


def parse_api_key_permissions(values: list[str]) -> frozenset[ApiKeyPermission]:
    """Fails closed: an unrecognized string (typo, a permission removed
    in a later release, a corrupted stored payload) is silently dropped
    rather than granted -- matches app.role_hierarchy.parse_membership_role's
    own fail-closed convention for unparseable enum values."""
    parsed: set[ApiKeyPermission] = set()
    for value in values:
        try:
            parsed.add(ApiKeyPermission(value))
        except ValueError:
            continue
    return frozenset(parsed)
