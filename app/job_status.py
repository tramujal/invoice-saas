"""BackgroundJob lifecycle states -- see app.services.background_jobs for
the centralized state-machine transition helper that enforces which of
these moves are legal. Never written to directly by handler code; always
through that helper, so an invalid transition is a bug caught at the one
place responsible for it, not scattered across every job type."""

from enum import Enum


class JobStatus(str, Enum):
    pending = "pending"
    claimed = "claimed"
    running = "running"
    retry_scheduled = "retry_scheduled"
    succeeded = "succeeded"
    permanently_failed = "permanently_failed"
    cancelled = "cancelled"
