from enum import Enum


class ReminderType(str, Enum):
    before_due = "before_due"
    due_today = "due_today"
    after_due = "after_due"
    # A human (button click) or the AI Agent explicitly asked for this one,
    # right now -- not selected by the scheduled job's day-offset logic.
    # Shares one idempotency slot per invoice per calendar day (see the
    # unique constraint on InvoiceReminder), which is what actually
    # prevents rapid duplicate manual sends.
    manual = "manual"
