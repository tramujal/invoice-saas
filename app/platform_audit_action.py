from enum import Enum


class PlatformAuditAction(str, Enum):
    organization_suspended = "organization.suspended"
    organization_reactivated = "organization.reactivated"
    user_disabled = "user.disabled"
    user_enabled = "user.enabled"
    user_email_verified = "user.email_verified"
    user_password_reset_requested = "user.password_reset_requested"
    user_platform_role_granted = "user.platform_role_granted"
    user_platform_role_revoked = "user.platform_role_revoked"
    platform_settings_updated = "platform.settings_updated"
    plan_created = "platform.plan_created"
    plan_updated = "platform.plan_updated"
    plan_activated = "platform.plan_activated"
    plan_deactivated = "platform.plan_deactivated"
    plan_default_changed = "platform.plan_default_changed"
    organization_plan_changed = "organization.plan_changed"
