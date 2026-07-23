"""Pure-logic coverage for app.platform_permissions -- no HTTP, no
database. See tests/permissions/test_platform_role_matrix.py for the
end-to-end proof that routers actually call require_platform_permission.
"""

import pytest

from app.platform_permissions import (
    PLATFORM_ROLE_PERMISSIONS,
    PlatformPermission,
    PlatformRole,
    check_platform_permission,
)


def test_super_admin_holds_every_platform_permission():
    """MVP scope: PlatformRole.super_admin is the only role today, and it
    must grant everything -- a future narrower role (e.g. read-only
    "support") should never reduce what super_admin can already do."""
    assert PLATFORM_ROLE_PERMISSIONS[PlatformRole.super_admin] == frozenset(PlatformPermission)


@pytest.mark.parametrize("permission", list(PlatformPermission))
def test_check_platform_permission_true_for_super_admin(permission):
    assert check_platform_permission(PlatformRole.super_admin, permission) is True


def test_platform_role_has_exactly_one_member_in_mvp():
    """Documents the deliberate MVP simplification (a single SUPER_ADMIN
    role) -- this test is expected to start failing, informatively, the
    moment a second role (e.g. a narrower "support" role) is introduced,
    which is the point at which PLATFORM_ROLE_PERMISSIONS's additivity
    actually gets exercised for the first time."""
    assert list(PlatformRole) == [PlatformRole.super_admin]


def test_no_support_mode_or_org_delete_permission_exists_yet():
    """Support-mode impersonation and organization deletion are
    explicitly postponed (see the Phase 13 proposal) -- this test fails
    loudly if either is added without a deliberate decision to do so."""
    permission_values = {p.value for p in PlatformPermission}
    assert "platform.support_mode.use" not in permission_values
    assert "platform.organizations.delete" not in permission_values
