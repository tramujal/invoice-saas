from enum import Enum


class MembershipStatus(str, Enum):
    active = "active"
    # Soft only -- removing a member never deletes data, only flips this.
    # The row (and its invited_by/accepted_at audit trail) is kept forever;
    # see app.services.team.remove_member_record.
    removed = "removed"
