"""Immediate, best-effort webhook delivery dispatch -- triggered the
moment a business transaction that emitted a WebhookEvent actually
commits, via a SQLAlchemy Session `after_commit` hook, never via FastAPI's
BackgroundTasks.

Why not BackgroundTasks: BackgroundTasks requires a `Request`/
`BackgroundTasks` parameter threaded through the exact function that
knows a delivery needs to happen -- but webhook events are emitted from
deep inside shared service functions (app.services.customers,
app.services.products, app.services.quotes, app.services.invoices) that
are each called from FIVE independently-owned entry points: the browser
routers, the public /api/v1 routers, the AI assistant's tool-execution
path (no Request object at all, several call layers removed from any
router), the CSV/XLSX import confirm endpoints, and the platform-admin
router. Threading BackgroundTasks through all of them would mean changing
every one of those shared service functions' signatures -- exactly the
kind of restructuring this phase's "reuse existing services, never
redesign them" rule forbids. This app also has no other shared
post-commit execution mechanism today (inspected: BackgroundTasks is
used in app.routers.auth, always fed by a single router with a `Request`
in scope -- not a fit here).

Dispatch is instead a property of the persistence layer itself: the
moment ANY commit succeeds, this module checks whether that commit just
made new WebhookDelivery rows durable (tracked via Session.info, set by
app.services.webhook_events.record_webhook_event) and, if so, submits
each one to a small worker thread pool for actual HTTP delivery. This is
reactive, one-shot dispatch -- never a poller, never a scheduler, never a
retry loop: exactly one delivery attempt is scheduled per row here, and
this module has no code path that ever re-submits a delivery on its own
(manual resend -- app.services.webhook_deliveries.resend_delivery --
creates a brand-new row and calls schedule_delivery for THAT row
explicitly; nothing here loops or polls for retryable rows).

Each worker opens its own SessionLocal() (never the request's session,
which may already be closed by the time the thread runs) -- the same
established convention as app.routers.auth's
_issue_email_verification_task/_issue_password_reset_task background-task
functions.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.database import SessionLocal

logger = logging.getLogger(__name__)

_SESSION_INFO_KEY = "_pending_webhook_delivery_ids"

# Small, fixed pool -- outbound webhook delivery is I/O-bound network work,
# never CPU-bound, and this app runs as a single process (see
# app.rate_limit's own docstring on the same deployment fact), so a fixed
# thread pool is enough without needing a queue depth/backpressure story
# beyond what ThreadPoolExecutor already provides (submissions queue
# internally rather than blocking the caller).
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook-delivery")


def mark_for_dispatch(db: Session, delivery_id: str) -> None:
    """Records intent to dispatch `delivery_id` once (and only if) the
    CURRENT transaction actually commits -- called right after a new
    pending WebhookDelivery row is added (see
    app.services.webhook_events.record_webhook_event). Session.info is a
    plain dict SQLAlchemy attaches to the Session for exactly this kind
    of request-scoped bookkeeping; it is never read by anything except
    the after_commit hook below."""
    db.info.setdefault(_SESSION_INFO_KEY, []).append(delivery_id)


def schedule_delivery(delivery_id: str) -> None:
    """Submits one delivery attempt to the worker pool immediately.
    Called directly by the manual-resend endpoint (whose own commit has
    already succeeded by the time it calls this) and, indirectly, by the
    after_commit hook below for automatic deliveries."""
    _executor.submit(_run_delivery, delivery_id)


def _run_delivery(delivery_id: str) -> None:
    # Local import: app.services.webhook_deliveries imports app.models and
    # the signing/SSRF helpers, none of which import this module -- so
    # this isn't strictly required to avoid a cycle, but keeps the import
    # graph the same shape as auth.py's own lazy-inside-the-task-function
    # convention for infrastructure only the background path needs.
    from app.services.webhook_deliveries import deliver_webhook

    db = SessionLocal()
    try:
        deliver_webhook(db, delivery_id)
    except Exception:
        logger.exception(
            "webhook_dispatch: delivery attempt raised unexpectedly delivery_id=%s", delivery_id
        )
    finally:
        db.close()


@event.listens_for(Session, "after_commit")
def _dispatch_after_commit(session: Session) -> None:
    delivery_ids = session.info.pop(_SESSION_INFO_KEY, None)
    if not delivery_ids:
        return
    for delivery_id in delivery_ids:
        schedule_delivery(delivery_id)
