"""Job-type handler modules -- each one calls app.jobs.registry.register_job
at import time, so importing this package (see app.jobs.bootstrap) is what
actually populates the registry. A handler module never imports the worker
or the enqueue service at module level beyond what it needs to do its own
job's work, keeping the import graph one-directional: bootstrap -> handlers
-> domain services, never the reverse.
"""

from app.jobs.handlers import notification, webhook, whatsapp  # noqa: F401
