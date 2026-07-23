"""Scheduled payment-reminder job.

Run as: python -m app.jobs.send_due_invoice_reminders [--dry-run]

Deliberately a standalone script, never invoked from inside the FastAPI web
process and never exposed as an HTTP endpoint -- see the plan's "Scheduling
/ deployment" decision. Triggered externally on a schedule (a GitHub
Actions workflow in this repo -- see .github/workflows/send-invoice-
reminders.yml -- or a Render Cron Job on a paid plan, documented in
render.yaml).

For each organization with reminders_enabled=True, this computes the
organization's own local "today" and, for each of its configured before/
on/after-due offsets, runs one bounded, indexed query for invoices whose
due_date lands exactly on the target date and are not yet paid. Every
candidate goes through app.services.invoices.claim_and_send_reminder --
the exact same claim -> re-validate -> send -> update sequence the manual
button and the AI agent use -- so a reminder can never be sent twice for
the same (invoice, reminder_type, day) no matter how many processes race
to run this job at once.

Logs only counts and hashed identifiers, never raw emails or invoice
content (matching app.routers.assistant's _hash_for_log convention).
Exits non-zero only on a genuinely fatal error (e.g. the database is
unreachable); any individual send failure is logged and counted, never
fatal to the batch.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import Invoice, InvoiceReminder, Organization, init_db
from app.org_time import get_organization_today
from app.organization_status import OrganizationStatus
from app.payment_status import PaymentStatus
from app.reminder_settings import parse_day_list
from app.reminder_status import ReminderStatus
from app.reminder_type import ReminderType
from app.services.platform_settings import get_effective_settings
from app.services.invoices import (
    CustomerEmailMissingError,
    InvoiceAlreadyPaidError,
    InvoiceDueDateMissingError,
    ReminderAlreadySentError,
    ReminderSendFailedError,
    claim_and_send_reminder,
)

logger = logging.getLogger(__name__)


def _hash_for_log(value: str) -> str:
    """Never logs a raw organization/invoice id -- only a short, stable,
    non-reversible fingerprint, matching app.routers.assistant's own
    logging convention."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

# How long a reminder row can sit in "pending" before this job treats the
# claim as abandoned (e.g. a crash between the claim commit and the send)
# rather than in-flight. Far longer than a single run should ever take --
# see the plan's documented, accepted residual risk: sweeping a truly
# stale claim could rarely cause one duplicate reminder rather than a
# permanently-silent one, which is the smaller harm for a courtesy email.
STALE_PENDING_GRACE_MINUTES = 10


class _CandidateSpec:
    __slots__ = ("reminder_type", "days_offset", "target_due_date")

    def __init__(self, reminder_type: ReminderType, days_offset: int, target_due_date):
        self.reminder_type = reminder_type
        self.days_offset = days_offset
        self.target_due_date = target_due_date


def _candidate_specs(organization: Organization) -> list[_CandidateSpec]:
    today_local = get_organization_today(organization)
    specs: list[_CandidateSpec] = []

    for days in parse_day_list(organization.reminder_before_due_days):
        specs.append(
            _CandidateSpec(ReminderType.before_due, days, today_local + timedelta(days=days))
        )

    if organization.reminder_on_due_date:
        specs.append(_CandidateSpec(ReminderType.due_today, 0, today_local))

    for days in parse_day_list(organization.reminder_after_due_days):
        specs.append(
            _CandidateSpec(ReminderType.after_due, days, today_local - timedelta(days=days))
        )

    return specs


def _sweep_stale_pending(db) -> int:
    """Fails any reminder row that's been stuck 'pending' for longer than
    STALE_PENDING_GRACE_MINUTES -- see the module docstring's residual-risk
    note. Never runs in --dry-run mode."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PENDING_GRACE_MINUTES)
    stale_rows = db.scalars(
        select(InvoiceReminder).where(
            InvoiceReminder.status == ReminderStatus.pending.value,
            InvoiceReminder.created_at < cutoff,
        )
    ).all()
    for row in stale_rows:
        row.status = ReminderStatus.failed.value
        row.failure_code = "stale_pending_claim"
    if stale_rows:
        db.commit()
    return len(stale_rows)


def run(dry_run: bool) -> int:
    """Returns the number of reminders actually sent (0 in --dry-run)."""
    db = SessionLocal()
    sent_count = 0
    skipped_count = 0
    failed_count = 0
    candidate_count = 0

    try:
        # Global kill switches (see app.services.platform_settings) --
        # maintenance mode overrides everything else (no sending of any
        # kind while the platform is down for maintenance), and
        # invoice_reminders_enabled is the top-level toggle independent
        # of any organization's own reminders_enabled setting. Checked
        # before any query runs, not per-organization -- when either is
        # false, this entire run is a no-op.
        settings = get_effective_settings(db)
        if settings.maintenance_mode or not settings.invoice_reminders_enabled:
            logger.info(
                "send_due_invoice_reminders: skipped entire run "
                "maintenance_mode=%s invoice_reminders_enabled=%s",
                settings.maintenance_mode,
                settings.invoice_reminders_enabled,
            )
            return 0

        # Suspended organizations (see app.organization_status) are
        # excluded outright -- there's no product reason to keep emailing
        # a frozen tenant's customers on its behalf.
        organizations = db.scalars(
            select(Organization).where(
                Organization.reminders_enabled.is_(True),
                Organization.status == OrganizationStatus.active.value,
            )
        ).all()

        for organization in organizations:
            org_hash = _hash_for_log(organization.id)
            for spec in _candidate_specs(organization):
                invoices = db.scalars(
                    select(Invoice)
                    .options(selectinload(Invoice.customer))
                    .where(
                        Invoice.organization_id == organization.id,
                        Invoice.due_date == spec.target_due_date,
                        Invoice.payment_status != PaymentStatus.paid.value,
                    )
                ).all()

                for invoice in invoices:
                    candidate_count += 1
                    if dry_run:
                        continue

                    invoice_hash = _hash_for_log(invoice.id)
                    try:
                        claim_and_send_reminder(
                            db,
                            organization=organization,
                            invoice=invoice,
                            reminder_type=spec.reminder_type,
                            days_offset=spec.days_offset,
                            scheduled_for_date=get_organization_today(organization),
                            triggered_by="scheduled",
                        )
                        sent_count += 1
                    except (
                        ReminderAlreadySentError,
                        InvoiceAlreadyPaidError,
                        InvoiceDueDateMissingError,
                        CustomerEmailMissingError,
                    ) as exc:
                        skipped_count += 1
                        logger.info(
                            "send_due_invoice_reminders: skipped org_hash=%s "
                            "invoice_hash=%s reminder_type=%s reason=%s",
                            org_hash,
                            invoice_hash,
                            spec.reminder_type.value,
                            type(exc).__name__,
                        )
                    except ReminderSendFailedError:
                        # Already logged with full detail inside
                        # claim_and_send_reminder -- one failure never
                        # aborts the rest of the batch.
                        failed_count += 1

        stale_swept = 0 if dry_run else _sweep_stale_pending(db)

        logger.info(
            "send_due_invoice_reminders: run complete dry_run=%s organizations=%d "
            "candidates=%d sent=%d skipped=%d failed=%d stale_swept=%d",
            dry_run,
            len(organizations),
            candidate_count,
            sent_count,
            skipped_count,
            failed_count,
            stale_swept,
        )
        return sent_count
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Send due invoice payment reminders.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and log candidates without claiming or sending anything.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    try:
        init_db()
        run(dry_run=args.dry_run)
    except Exception:
        logger.exception("send_due_invoice_reminders: fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
