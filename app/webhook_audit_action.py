from enum import Enum


class WebhookAuditAction(str, Enum):
    endpoint_created = "webhook_endpoint.created"
    endpoint_updated = "webhook_endpoint.updated"
    endpoint_enabled = "webhook_endpoint.enabled"
    endpoint_disabled = "webhook_endpoint.disabled"
    endpoint_secret_rotated = "webhook_endpoint.secret_rotated"
    endpoint_archived = "webhook_endpoint.archived"
    delivery_resent = "webhook_delivery.resent"
