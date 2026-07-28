from enum import Enum


class ApiKeyAuditAction(str, Enum):
    key_created = "api_key.created"
    key_rotated = "api_key.rotated"
    key_revoked = "api_key.revoked"
    auth_failed = "api_key.auth_failed"
    revoked_key_used = "api_key.revoked_key_used"
    expired_key_used = "api_key.expired_key_used"
    permission_denied = "api_key.permission_denied"
