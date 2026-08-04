from enum import Enum


class WhatsAppIdentityStatus(str, Enum):
    """Lifecycle of one phone-number-to-user link (see app.models
    .WhatsAppIdentity). `pending` means a one-time verification code has
    been issued but not yet confirmed from that WhatsApp number; `verified`
    means the phone may act as this user in this organization; `disabled`
    means an admin (or the user themself) revoked it -- a disabled row is
    never deleted, only flipped to this status, so the audit trail of
    "this phone used to be linked" survives revocation."""

    pending = "pending"
    verified = "verified"
    disabled = "disabled"
