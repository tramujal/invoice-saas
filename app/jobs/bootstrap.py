"""Import this module (never `app.jobs.handlers` directly) anywhere the
job registry must be populated before use -- app.services.background_jobs
.enqueue_job and app.jobs.worker's entry point both import this at module
load time. A plain import, not a function call: Python only runs a
module's top-level code once per process, so this is naturally idempotent
regardless of how many places import it."""

import app.jobs.handlers  # noqa: F401
