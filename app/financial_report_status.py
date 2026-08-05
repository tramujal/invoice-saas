from enum import Enum


class FinancialReportStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
