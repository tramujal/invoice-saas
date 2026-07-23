"""Centralizes every actor-rank-vs-target-rank comparison for organization
role management -- the single place that answers "is actor senior enough to
do this," so app.services.team (and nowhere else) never repeats a numeric
role comparison. This is deliberately a separate module from
app.permissions: that file answers "what can this role do in general"
(a static, role-keyed capability set); this file answers "can THIS actor
act on THAT specific other role" (a relational comparison between two
roles), which is a materially different question with its own two
functions (can_manage_member, can_assign_role) rather than a capability set.

viewer < member < admin < owner. Multiple members may hold "owner"
simultaneously (see app.models.OrganizationMember's docstring) -- owner is
just the top rank, not a singleton.
"""

from app.membership_role import MembershipRole

ROLE_RANK: dict[MembershipRole, int] = {
    MembershipRole.viewer: 0,
    MembershipRole.member: 1,
    MembershipRole.admin: 2,
    MembershipRole.owner: 3,
}


def parse_membership_role(value: str) -> MembershipRole | None:
    """Fail-closed conversion from a raw DB string to MembershipRole --
    returns None (never raises) for a hand-edited or corrupted role value,
    so every caller here is forced to handle "unknown role" as its own
    case rather than letting ValueError escape as an unhandled 500."""
    try:
        return MembershipRole(value)
    except ValueError:
        return None


def role_rank(role: MembershipRole | None) -> int:
    """-1 for an unparseable/unknown role -- lower than viewer's 0, so an
    actor with a corrupted role can never out-rank anyone, and (via
    can_manage_member below) a target with a corrupted role can never be
    out-ranked by anyone either, since role_rank(None) also fails the
    equality special-case. Both directions fail closed."""
    if role is None:
        return -1
    return ROLE_RANK[role]


def can_manage_member(actor_role: MembershipRole | None, target_role: MembershipRole | None) -> bool:
    """Whether actor_role may modify or remove an *other* member currently
    holding target_role at all -- independent of what new role (if any)
    would be assigned; see can_assign_role for that half. Never call this
    for a target that is the actor themself: self-modification is exempt
    from the "equal-or-higher blocked" rule by design (a user may demote
    or remove themselves, subject only to can_assign_role and the
    last-owner invariant enforced separately in app.services.team) --
    the required rule is about "another user," not the actor's own row.

    A target whose role is unparseable is always protected (never
    manageable by anyone) -- the safe direction to fail closed, since
    otherwise a corrupted role value could accidentally look "low rank"
    and become modifiable by everyone.

    owner-vs-owner is the one explicit equal-rank exception: an owner may
    manage another owner, but only through the ordinary owner-gated
    actions in app.services.team (change_member_role_record /
    remove_member_record), which independently require the actor to
    already hold organization.manage (owner-only) and preserve the
    "at least one active owner" invariant -- those two guards together
    are what the spec calls the "explicit owner-management flow." This
    function only decides the rank question; the flow's other guards are
    unaffected by it.
    """
    if actor_role is None or target_role is None:
        return False
    if actor_role is MembershipRole.owner and target_role is MembershipRole.owner:
        return True
    return role_rank(actor_role) > role_rank(target_role)


def can_assign_role(actor_role: MembershipRole | None, requested_role: MembershipRole) -> bool:
    """Whether actor_role may set someone's (including the actor's own)
    role to requested_role. Strictly actor's rank > requested rank -- this
    single comparison is what makes "admin may assign only member or
    viewer" (never admin, never owner), "owner may assign admin/member/
    viewer" (never owner -- that's only possible via the dedicated
    grant-ownership flow), and "a user may never promote themselves" all
    fall out of one rule: you can never hand out a role at or above your
    own rank, whether the recipient is someone else or yourself."""
    if actor_role is None:
        return False
    return role_rank(actor_role) > role_rank(requested_role)
