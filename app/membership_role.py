from enum import Enum


class MembershipRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class InvitationRole(str, Enum):
    """Narrower than MembershipRole -- deliberately excludes "owner" so an
    invitation (or an ordinary role-change request) can never grant
    ownership at the type level. Ownership can only be granted through the
    dedicated, owner-gated grant-ownership action -- see
    app.services.team.grant_ownership_record."""

    admin = "admin"
    member = "member"
    viewer = "viewer"
