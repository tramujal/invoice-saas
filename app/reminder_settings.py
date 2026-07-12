"""Reminder day-offset lists are stored as a plain comma-separated string
column (e.g. "7,3,1") rather than a native array type -- this app runs on
both SQLite (dev) and Postgres (prod), and SQLite has no portable array
type, so a validated string is the safe, portable representation, exactly
like payment_status/currency_code are already plain validated strings
rather than native DB enums.
"""

REMINDER_DAY_MIN = 1
REMINDER_DAY_MAX = 90
REMINDER_DAY_LIST_MAX_LENGTH = 5


def parse_day_list(raw: str) -> list[int]:
    """Parses a stored "7,3,1" string into [7, 3, 1]. Never raises on
    malformed data -- silently drops any entry that isn't a valid,
    in-bounds integer, since this is read on every reminder-job run and
    must never crash the batch over one bad stored value."""
    if not raw or not raw.strip():
        return []
    days: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        value = int(part)
        if REMINDER_DAY_MIN <= value <= REMINDER_DAY_MAX:
            days.append(value)
    return days


def format_day_list(days: list[int]) -> str:
    return ",".join(str(d) for d in days)
