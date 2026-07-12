from enum import Enum


class ReminderStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    skipped = "skipped"
    failed = "failed"
