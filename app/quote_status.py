from enum import Enum


class QuoteStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"
    # Only ever returned by app.quote_effective_status.get_effective_quote_status
    # -- never stored. See that module's docstring.
    expired = "expired"
    converted = "converted"
