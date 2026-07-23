"""Scheduled quote-expiry reminder job.

Run as: python -m app.jobs.send_expiring_quote_reminders [--dry-run]

Mirrors app/jobs/send_due_invoice_reminders.py's exact structure and
rationale -- a standalone script, never invoked from inside the FastAPI
web process, triggered externally on a schedule (see
.github/workflows/send-invoice-reminders.yml, which runs this alongside
the invoice reminder job).

For each organization with quote_reminders_enabled=True, this computes the
organization's own local "today" and, for each of its configured
before-expiry offsets, runs one bounded query for quotes whose
expiry_date lands exactly on the target date and are still effectively
"sent". Every candidate goes through
app.services.quotes.claim_and_send_quote_reminder -- the same claim ->
re-validate -> send -> update sequence the invoice reminder job uses --
so a reminder can never be sent twice for the same (quote, day) no matter
how many processes race to run this job at once.
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
from app.models import Organization, Quote, QuoteReminder, init_db
from app.org_time import get_organization_today
from app.organization_status import OrganizationStatus
from app.quote_effective_status import get_effective_quote_status
from app.quote_status import QuoteStatus
from app.reminder_settings import parse_day_list
from app.reminder_status import ReminderStatus
from app.services.platform_settings import get_effective_settings
from app.services.quotes import (
    CustomerEmailMissingError,
    QuoteNotEligibleForReminderError,
    QuoteReminderAlreadySentError,
    QuoteReminderSendFailedError,
    claim_and_send_quote_reminder,
)

logger = logging.getLogger(__name__)

STALE_PENDING_GRACE_MINUTES = 10


def _hash_for_log(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _sweep_stale_pending(db) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PENDING_GRACE_MINUTES)
    stale_rows = db.scalars(
        select(QuoteReminder).where(
            QuoteReminder.status == ReminderStatus.pending.value,
            QuoteReminder.created_at < cutoff,
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
        # same rationale as send_due_invoice_reminders.py's identical
        # check: maintenance mode overrides everything, and
        # quote_reminders_enabled is the top-level toggle independent of
        # any organization's own quote_reminders_enabled setting.
        settings = get_effective_settings(db)
        if settings.maintenance_mode or not settings.quote_reminders_enabled:
            logger.info(
                "send_expiring_quote_reminders: skipped entire run "
                "maintenance_mode=%s quote_reminders_enabled=%s",
                settings.maintenance_mode,
                settings.quote_reminders_enabled,
            )
            return 0

        # Suspended organizations (see app.organization_status) are
        # excluded outright -- same rationale as the invoice-reminder job.
        organizations = db.scalars(
            select(Organization).where(
                Organization.quote_reminders_enabled.is_(True),
                Organization.status == OrganizationStatus.active.value,
            )
        ).all()

        for organization in organizations:
            org_hash = _hash_for_log(organization.id)
            today_local = get_organization_today(organization)

            for days in parse_day_list(organization.quote_reminder_before_expiry_days):
                target_expiry_date = today_local + timedelta(days=days)

                quotes = db.scalars(
                    select(Quote)
                    .options(selectinload(Quote.customer))
                    .where(
                        Quote.organization_id == organization.id,
                        Quote.active.is_(True),
                        Quote.status == QuoteStatus.sent.value,
                        Quote.expiry_date == target_expiry_date,
                    )
                ).all()

                for quote in quotes:
                    # Fresh re-check even before claiming -- expiry could
                    # already have flipped this quote to "expired" if
                    # target_expiry_date == today_local exactly (edge case
                    # at day boundary); claim_and_send_quote_reminder
                    # re-checks again immediately after the claim too.
                    if get_effective_quote_status(quote, today_local) != QuoteStatus.sent:
                        continue

                    candidate_count += 1
                    if dry_run:
                        continue

                    quote_hash = _hash_for_log(quote.id)
                    try:
                        claim_and_send_quote_reminder(
                            db,
                            organization=organization,
                            quote=quote,
                            days_offset=days,
                            scheduled_for_date=today_local,
                            triggered_by="scheduled",
                        )
                        sent_count += 1
                    except (
                        QuoteReminderAlreadySentError,
                        QuoteNotEligibleForReminderError,
                        CustomerEmailMissingError,
                    ) as exc:
                        skipped_count += 1
                        logger.info(
                            "send_expiring_quote_reminders: skipped org_hash=%s "
                            "quote_hash=%s reason=%s",
                            org_hash,
                            quote_hash,
                            type(exc).__name__,
                        )
                    except QuoteReminderSendFailedError:
                        failed_count += 1

        stale_swept = 0 if dry_run else _sweep_stale_pending(db)

        logger.info(
            "send_expiring_quote_reminders: run complete dry_run=%s organizations=%d "
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
    parser = argparse.ArgumentParser(description="Send expiring quote reminders.")
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
        logger.exception("send_expiring_quote_reminders: fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
