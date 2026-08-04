"""The whatsapp.send_document job handler (Phase 23) -- registered into
app.jobs.registry at import time (see this package's own __init__.py).
Mirrors app.jobs.handlers.notification/webhook's exact shape: the payload
carries only ids and small display strings (never PDF bytes), and the
handler re-fetches/re-renders everything it needs at execution time.

This is the one background job the experimental WhatsApp assistant uses
today -- see docs/whatsapp.md's "Background jobs" section for why voice
transcription and AI interpretation are deliberately NOT queued in this
phase (the in-process conversation context store, app.whatsapp
.context_store, cannot be shared with a separate worker process, so
moving those steps to a job would silently break multi-turn context).
PDF rendering and sending have no such dependency -- they're pure,
stateless, re-derivable-from-an-id work, exactly like every other queued
job in this app.
"""

import logging

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.invoice_pdf import render_invoice_pdf
from app.job_type import JobType
from app.jobs.registry import JobDefinition, JobOutcome, JobResult, register_job
from app.models import BackgroundJob, Invoice, Quote
from app.quote_pdf import render_quote_pdf
from app.whatsapp.provider_base import WhatsAppBridgeUnavailableError, WhatsAppNotConfiguredError, WhatsAppProviderError
from app.whatsapp.provider_factory import get_whatsapp_provider

logger = logging.getLogger(__name__)


class WhatsAppSendDocumentPayload(BaseModel):
    document_type: str  # "invoice" | "quote"
    document_id: str
    phone_number: str
    document_number: str


def _safe_filename(document_type: str, document_number: str) -> str:
    # document_number is always this app's own formatted number
    # ("INV-000145"/"QUO-000120", see app.invoice_numbering/
    # app.quote_numbering) -- never a caller-supplied string, so no path-
    # traversal/arbitrary-filesystem-access concern, but still sanitized
    # defensively since this becomes a filename a WhatsApp client renders.
    safe = "".join(ch for ch in document_number if ch.isalnum() or ch in ("-", "_"))
    return f"{safe or document_type}.pdf"


def handle_whatsapp_send_document(
    db: Session, job: BackgroundJob, payload: WhatsAppSendDocumentPayload
) -> JobResult:
    if payload.document_type == "invoice":
        document = db.get(Invoice, payload.document_id)
    elif payload.document_type == "quote":
        document = db.get(Quote, payload.document_id)
    else:
        return JobResult(
            outcome=JobOutcome.permanently_failed,
            error_code="invalid_document_type",
            error_message=f"Unknown document_type {payload.document_type!r}.",
        )

    if document is None:
        # Unreachable in normal operation (invoices/quotes are never hard-
        # deleted once created), but a genuine job-execution problem if it
        # ever happens -- mirrors handle_webhook_retry's own "referenced
        # row is gone" handling.
        return JobResult(
            outcome=JobOutcome.permanently_failed,
            error_code="document_missing",
            error_message="Referenced invoice/quote no longer exists.",
        )

    try:
        pdf_bytes = render_invoice_pdf(document) if payload.document_type == "invoice" else render_quote_pdf(document)
    except Exception as exc:  # pragma: no cover - defensive; PDF rendering is otherwise pure
        return JobResult(
            outcome=JobOutcome.permanently_failed,
            error_code="pdf_render_failed",
            error_message=str(exc),
        )

    try:
        provider = get_whatsapp_provider()
        provider.send_document(
            payload.phone_number,
            _safe_filename(payload.document_type, payload.document_number),
            pdf_bytes,
            "application/pdf",
        )
    except WhatsAppNotConfiguredError:
        # Transport got disabled/unconfigured between enqueue and
        # execution -- a platform-config condition, not transient, so
        # retrying on the generic backoff would never fix it (mirrors
        # handle_notification_email's identical "email_not_configured"
        # treatment).
        return JobResult(
            outcome=JobOutcome.permanently_failed,
            error_code="whatsapp_not_configured",
            error_message="WhatsApp transport is disabled or unconfigured.",
        )
    except WhatsAppBridgeUnavailableError:
        # The bridge being temporarily down is exactly the transient,
        # retryable case the generic job backoff exists for.
        return JobResult(outcome=JobOutcome.retry, error_message="WhatsApp bridge unavailable.")
    except WhatsAppProviderError as exc:
        return JobResult(outcome=JobOutcome.retry, error_message=str(exc))

    return JobResult(outcome=JobOutcome.succeeded, result_summary=f"sent document={payload.document_number}")


register_job(
    JobDefinition(
        job_type=JobType.whatsapp_send_document,
        payload_schema=WhatsAppSendDocumentPayload,
        handler=handle_whatsapp_send_document,
        queue="default",
        priority=0,
        max_attempts=5,
        timeout_seconds=30,
        organization_id_required=True,
    )
)
