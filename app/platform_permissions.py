"""The single source of truth for what a platform-administration role may
do -- the SaaS-operator authorization axis. Mirrors app.permissions's
shape exactly, but is entirely independent from it: app.permissions
governs what a user may do *inside a specific organization* they belong
to (via OrganizationMember.role); this module governs platform-wide
operator actions and never involves an organization_id at all. See
app.deps.require_platform_permission for the enforcement side.

MVP note: only PlatformRole.super_admin exists today, holding every
PlatformPermission. The map is still additive/extensible (same shape as
app.permissions.ROLE_PERMISSIONS) so a future narrower role (e.g. a
read-only "support" role) can be introduced later with zero changes to
callers -- they already check permissions, never role names. Support-mode
impersonation and organization deletion are deliberately out of scope for
this phase; no permission for either exists yet.
"""

from enum import Enum


class PlatformRole(str, Enum):
    super_admin = "super_admin"


class PlatformPermission(str, Enum):
    dashboard_view = "platform.dashboard.view"
    organizations_view = "platform.organizations.view"
    organizations_manage = "platform.organizations.manage"  # suspend/reactivate only -- no delete
    users_view = "platform.users.view"
    users_manage = "platform.users.manage"  # reset password, force-verify, disable
    settings_view = "platform.settings.view"  # read the System Settings page
    settings_manage = "platform.settings.manage"  # reserved: future settings *writes*
    audit_view = "platform.audit.view"
    roles_manage = "platform.roles.manage"  # grant/revoke platform_role
    plans_view = "platform.plans.view"
    plans_manage = "platform.plans.manage"  # create/edit/activate/deactivate/make-default


_SUPER_ADMIN_PERMISSIONS: frozenset[PlatformPermission] = frozenset(PlatformPermission)

PLATFORM_ROLE_PERMISSIONS: dict[PlatformRole, frozenset[PlatformPermission]] = {
    PlatformRole.super_admin: _SUPER_ADMIN_PERMISSIONS,
}


def check_platform_permission(role: PlatformRole, permission: PlatformPermission) -> bool:
    return permission in PLATFORM_ROLE_PERMISSIONS[role]
