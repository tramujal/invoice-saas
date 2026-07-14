"""Organization invitation email content.

Mirrors app.email.quote_templates's conventions exactly: plain-text,
t()-driven, no attachments. Uses the organization's configured language
(get_language(organization)) rather than any personal preference of the
invitee -- unlike a password reset or email verification, there is no
"language the visitor was viewing" to fall back to here (the invitee may
never have seen this app before), so the inviting organization's own
language setting is the most sensible default for how it communicates.
"""

from app.localization import get_language, t
from app.models import Organization, OrganizationInvitation, OrganizationMember, User


def _role_label(language: str, role: str) -> str:
    return t(language, f"membership_role_{role}")


def build_invitation_email(
    invitation: OrganizationInvitation,
    organization: Organization,
    inviter: User | None,
    accept_link: str,
) -> tuple[str, str]:
    """Returns (subject, plain-text body) for a team invitation email."""
    language = get_language(organization)
    org_name = organization.business_name or organization.name
    inviter_email = inviter.email if inviter is not None else org_name
    role_label = _role_label(language, invitation.role)

    subject = t(language, "invitation_subject").format(organization=org_name)
    body = (
        f"{t(language, 'invitation_greeting')}\n"
        "\n"
        f"{t(language, 'invitation_intro').format(inviter=inviter_email, organization=org_name, role=role_label)}\n"
        "\n"
        f"{t(language, 'invitation_accept_label')}\n"
        f"{accept_link}\n"
        "\n"
        f"{t(language, 'invitation_expiry')}\n"
        "\n"
        f"{t(language, 'invitation_ignore')}"
    )
    return subject, body


def build_invitation_accepted_email(
    organization: Organization, new_member: OrganizationMember, inviter: User | None
) -> tuple[str, str]:
    """Returns (subject, plain-text body) notifying the inviter that their
    invitation was accepted."""
    language = get_language(organization)
    org_name = organization.business_name or organization.name
    role_label = _role_label(language, new_member.role)

    subject = t(language, "invitation_accepted_subject").format(organization=org_name)
    body = (
        f"{t(language, 'invitation_accepted_greeting')}\n"
        "\n"
        f"{t(language, 'invitation_accepted_body').format(email=new_member.user_email, role=role_label, organization=org_name)}\n"
        "\n"
        f"{t(language, 'email_thanks')}"
    )
    return subject, body
