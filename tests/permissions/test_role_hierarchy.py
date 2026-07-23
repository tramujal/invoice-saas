"""Pure unit tests for app.role_hierarchy -- the single place every
actor-rank-vs-target-rank comparison in app.services.team goes through.
Router-level behavior driven by these same functions is covered in
test_role_matrix.py; this file exists to pin down the underlying rules
(including the fail-closed corrupted-role cases) independent of HTTP."""

from app.membership_role import MembershipRole
from app.role_hierarchy import can_assign_role, can_manage_member, parse_membership_role, role_rank

OWNER, ADMIN, MEMBER, VIEWER = (
    MembershipRole.owner,
    MembershipRole.admin,
    MembershipRole.member,
    MembershipRole.viewer,
)


def test_role_rank_orders_the_hierarchy():
    assert role_rank(VIEWER) < role_rank(MEMBER) < role_rank(ADMIN) < role_rank(OWNER)


def test_role_rank_of_unparseable_role_is_lowest():
    assert role_rank(None) < role_rank(VIEWER)


def test_parse_membership_role_fails_closed_on_garbage():
    assert parse_membership_role("not_a_role") is None
    assert parse_membership_role("owner") is OWNER


def test_can_assign_role_blocks_assigning_own_rank_or_higher():
    assert can_assign_role(ADMIN, MEMBER) is True
    assert can_assign_role(ADMIN, VIEWER) is True
    assert can_assign_role(ADMIN, ADMIN) is False
    assert can_assign_role(OWNER, ADMIN) is True
    assert can_assign_role(OWNER, OWNER) is False


def test_can_assign_role_fails_closed_for_unparseable_actor():
    assert can_assign_role(None, VIEWER) is False


def test_can_manage_member_blocks_equal_or_higher_rank():
    assert can_manage_member(ADMIN, MEMBER) is True
    assert can_manage_member(ADMIN, VIEWER) is True
    assert can_manage_member(ADMIN, ADMIN) is False
    assert can_manage_member(ADMIN, OWNER) is False
    assert can_manage_member(OWNER, ADMIN) is True


def test_can_manage_member_owner_vs_owner_is_the_one_equal_rank_exception():
    assert can_manage_member(OWNER, OWNER) is True


def test_can_manage_member_fails_closed_for_unparseable_either_side():
    assert can_manage_member(None, MEMBER) is False
    assert can_manage_member(ADMIN, None) is False
    assert can_manage_member(None, None) is False
