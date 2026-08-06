"""The complete, authoritative set of background-job types this worker
will execute -- see app.jobs.registry for the JobDefinition each of these
maps to (payload schema, handler, queue, priority, max attempts, retry
policy). A job row's `job_type` column stores this enum's `.value`; an
unrecognized string read back from the database is handled explicitly as
"unknown job type" (see app.jobs.registry.get_job_definition) rather than
ever being passed to `eval`, `import_module`, or any other dynamic-code
mechanism -- job types are a closed, server-side-only vocabulary, never
resolved from anything a caller supplies.
"""

from enum import Enum


class JobType(str, Enum):
    webhook_deliver = "webhook.deliver"
    webhook_retry = "webhook.retry"
    notification_email = "notification.email"
    # Phase 23 -- the experimental WhatsApp assistant. Re-renders the PDF
    # from document_id at execution time (never carries PDF bytes in the
    # payload) and sends it via the configured WhatsAppProvider -- see
    # app.jobs.handlers.whatsapp.
    whatsapp_send_document = "whatsapp.send_document"
    # Phase 24.3 -- the AI Financial Advisor. Generates one
    # FinancialInsightReport's structured analysis; the payload carries
    # only the report id (see app.jobs.handlers.financial_intelligence).
    financial_insight_generate = "financial_insight.generate"
