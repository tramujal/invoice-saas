from enum import Enum


class PaymentStatus(str, Enum):
    pending = "pending"
    paid = "paid"
    overdue = "overdue"
