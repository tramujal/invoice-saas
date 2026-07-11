from enum import Enum


class AssistantActionStatus(str, Enum):
    proposed = "proposed"
    executed = "executed"
    cancelled = "cancelled"
    expired = "expired"
    failed = "failed"
