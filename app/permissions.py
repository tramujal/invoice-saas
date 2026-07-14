"""The single source of truth for what each membership role may do.

Mirrors app.tokens's "pure, reusable primitive" philosophy: no FastAPI
import, no database access -- just an enum and a static role -> capability
map, callable from anywhere that needs an authorization decision (ordinary
HTTP routes via app.deps.require_permission, the AI Assistant's streaming
propose path, the AI Agent's confirm path, and any future surface). There
is exactly one place a new capability is defined and exactly one place a
role's grants are listed -- never a scattered `if role == ...` anywhere
else in the codebase.

Two things a single Permission value can't express live outside this map,
in app.services.team: (1) granting/revoking the "owner" role additionally
requires the *caller* to already hold organization.manage, and (2)
demoting or removing an owner-equivalent member additionally requires at
least one *other* active member with organization.manage to remain
afterward. Those are data-dependent invariants, not static role facts --
but even they never name a role directly, only a permission (via
roles_with_permission below), so a future custom role granted
organization.manage participates in both automatically.
"""

from enum import Enum

from app.membership_role import MembershipRole


class Permission(str, Enum):
    organization_manage = "organization.manage"  # owner-only: granting/revoking ownership
    members_manage = "members.manage"  # owner+admin: invite, ordinary role changes, remove non-owners, cancel/resend invite
    settings_manage = "settings.manage"  # owner+admin: PATCH organization profile
    billing_manage = "billing.manage"  # owner-only: reserved, unused today -- see app.services for future paid-plan integration

    customer_read = "customer.read"
    customer_write = "customer.write"
    product_read = "product.read"
    product_write = "product.write"
    invoice_read = "invoice.read"
    invoice_create = "invoice.create"
    invoice_edit = "invoice.edit"
    invoice_send = "invoice.send"
    quote_read = "quote.read"
    quote_create = "quote.create"
    # quote.edit/quote.send extend the spec's example permission list to
    # reach full router coverage -- they mirror invoice.edit/invoice.send's
    # existing shape exactly (quote.edit covers PATCH/duplicate/archive/
    # restore/delete/mark-accepted/mark-rejected; quote.send covers
    # send-email), following the same read/create/edit/send pattern
    # invoices already established.
    quote_edit = "quote.edit"
    quote_send = "quote.send"
    quote_convert = "quote.convert"

    assistant_chat = "assistant.chat"
    assistant_execute = "assistant.execute"
    dashboard_view = "dashboard.view"
    insights_view = "insights.view"


_VIEWER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.customer_read,
        Permission.product_read,
        Permission.invoice_read,
        Permission.quote_read,
        Permission.dashboard_view,
        Permission.insights_view,
        Permission.assistant_chat,
    }
)

_MEMBER_PERMISSIONS: frozenset[Permission] = _VIEWER_PERMISSIONS | frozenset(
    {
        Permission.customer_write,
        Permission.product_write,
        Permission.invoice_create,
        Permission.invoice_edit,
        Permission.invoice_send,
        Permission.quote_create,
        Permission.quote_edit,
        Permission.quote_send,
        Permission.quote_convert,
        Permission.assistant_execute,
    }
)

_ADMIN_PERMISSIONS: frozenset[Permission] = _MEMBER_PERMISSIONS | frozenset(
    {
        Permission.members_manage,
        Permission.settings_manage,
    }
)

# Owner gets everything, including organization.manage and billing.manage,
# which no other role ever holds.
_OWNER_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.viewer: _VIEWER_PERMISSIONS,
    MembershipRole.member: _MEMBER_PERMISSIONS,
    MembershipRole.admin: _ADMIN_PERMISSIONS,
    MembershipRole.owner: _OWNER_PERMISSIONS,
}


def check_permission(role: MembershipRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def roles_with_permission(permission: Permission) -> frozenset[MembershipRole]:
    """Every role that currently grants `permission`, derived from
    ROLE_PERMISSIONS -- the single place to ask "which roles can do X"
    instead of naming a specific role anywhere else in the codebase (e.g.
    "who counts as owner-equivalent for the ownership invariants" becomes
    roles_with_permission(Permission.organization_manage), not a hardcoded
    role == "owner" check). This is what lets a future custom role (Sales,
    Accountant, Support, Billing...) that happens to be granted a given
    permission participate correctly everywhere that permission is
    consulted, with zero changes outside this file."""
    return frozenset(role for role, permissions in ROLE_PERMISSIONS.items() if permission in permissions)
