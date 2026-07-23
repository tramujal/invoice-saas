"""User.status -- the account-level access axis, entirely independent of
both OrganizationMember.role (per-org authorization) and User.platform_role
(platform-administration authorization). A disabled user is blocked at the
shared current-user authentication dependency (see app.deps.get_current_user)
before either of those other two axes is ever consulted -- disabling is an
account-level access block, never a tenant-data mutation, so a disabled
user's memberships and organizations are left completely untouched.

Mirrors app.organization_status.OrganizationStatus's exact shape and
rationale."""

from enum import Enum


class UserStatus(str, Enum):
    active = "active"
    disabled = "disabled"
