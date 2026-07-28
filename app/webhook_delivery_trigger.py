"""How a WebhookDelivery row came to exist -- shown in the delivery-history
UI so an operator can tell "the platform sent this the moment the event
happened" apart from "someone clicked Resend." Never affects signing,
payload shape, or endpoint matching -- purely provenance."""

from enum import Enum


class WebhookDeliveryTrigger(str, Enum):
    automatic = "automatic"
    manual_resend = "manual_resend"
    automatic_retry = "automatic_retry"
