"""POST /billing/webhooks/{provider} -- receives incoming webhook
deliveries from a payment provider and drives Subscription state through
app.billing.service.BillingService.sync_from_webhook_event.

Public and unauthenticated (a payment provider cannot present a JWT) --
verified instead by BillingProvider.parse_webhook_event's own signature
check, the same "different verification mechanism, not no verification"
pattern app.routers.quote_public/invitation_public already use for their
own public, token-verified routes.

Only one concrete provider is ever active at a time in this phase (one
BILLING_PROVIDER env var) -- a route for a provider that isn't the
currently configured one 503s via get_billing_provider_dependency, same
as every other provider-dependent call. A future multi-provider-
simultaneously deployment (accepting webhooks from two providers at
once, e.g. mid-migration) would need a small resolution change here;
out of scope for this phase.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing.provider_base import (
    BillingProvider,
    BillingProviderRequestError,
    InvalidWebhookSignatureError,
    UnsupportedWebhookEventError,
)
from app.billing.service import BillingService, SubscriptionConflictError
from app.database import get_db
from app.deps import get_billing_provider_dependency
from app.models import ProviderWebhookReceipt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing/webhooks", tags=["billing-webhooks"])


@router.post("/stripe", status_code=status.HTTP_200_OK)
async def receive_stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    provider: BillingProvider = Depends(get_billing_provider_dependency),
) -> dict:
    payload = await request.body()
    signature_header = request.headers.get("stripe-signature", "")

    try:
        event = provider.parse_webhook_event(payload=payload, signature_header=signature_header)
    except InvalidWebhookSignatureError as exc:
        logger.warning("receive_stripe_webhook: invalid signature: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature") from exc
    except UnsupportedWebhookEventError as exc:
        # A real, expected occurrence -- Stripe fires many event types
        # this app never reacts to. Acknowledge (2xx) so Stripe stops
        # retrying; never a 400/500 for an event we simply don't handle.
        logger.info("receive_stripe_webhook: ignoring unsupported event type: %s", exc)
        return {"status": "ignored"}
    except BillingProviderRequestError as exc:
        logger.exception("receive_stripe_webhook: provider request failed while parsing event")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not verify webhook with provider"
        ) from exc

    existing_receipt = db.scalar(
        select(ProviderWebhookReceipt.id).where(
            ProviderWebhookReceipt.provider_name == event.provider_name,
            ProviderWebhookReceipt.event_id == event.event_id,
        )
    )
    if existing_receipt is not None:
        logger.info(
            "receive_stripe_webhook: duplicate delivery, already processed "
            "provider=%s event_id=%s",
            event.provider_name,
            event.event_id,
        )
        return {"status": "already_processed"}

    # Phase P2.2 (H5): added to the session BEFORE the mutation below,
    # not committed separately afterward -- BillingService.
    # sync_from_webhook_event's own commit (inside whichever
    # BillingService method it calls; see that method's own _commit)
    # flushes this pending row in the SAME transaction as the
    # subscription mutation it applies. That's what makes "the mutation
    # was applied" and "this event was recorded as processed" atomic:
    # either both land together, or (on any exception below) neither
    # does. Before this, the receipt was written in a SECOND, separate
    # commit strictly after the mutation's own commit already succeeded
    # -- a crash in between left a mutated Subscription with no receipt
    # on file, so a redelivery of the same event would reapply it a
    # second time (several BillingService methods, e.g.
    # cancel_immediately, are not idempotent against being called twice
    # -- each call writes its own new SubscriptionEvent row).
    db.add(ProviderWebhookReceipt(provider_name=event.provider_name, event_id=event.event_id))

    try:
        BillingService(db, provider=provider).sync_from_webhook_event(event)
    except (LookupError, ValueError) as exc:
        # A structurally unresolvable event (unknown organization/plan/
        # provider_reference) -- raised before any mutating commit runs
        # (see sync_from_webhook_event's own branches), so this rollback
        # discards the pending receipt too. Never recorded as processed,
        # so a legitimate redelivery (e.g. after we fix a data issue) can
        # still be retried. Stripe will retry a non-2xx response on its
        # own schedule.
        db.rollback()
        logger.error(
            "receive_stripe_webhook: could not apply event provider=%s event_id=%s error=%s",
            event.provider_name,
            event.event_id,
            exc,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SubscriptionConflictError as exc:
        # This event's own subscription row was concurrently modified by
        # another writer (a platform-admin action, or another webhook
        # event for the same subscription processed by a different
        # worker) between this handler's read and its own commit.
        # BillingService's own _commit already rolls back internally
        # before raising this (see that method's own docstring), but
        # rolling back again here too is cheap, safe, and doesn't rely on
        # remembering that internal detail -- either way, our pending
        # receipt is discarded, never recorded as processed. Deliberately
        # NOT retried in-process (the subscription's true current state
        # may have moved in a way that makes blindly re-applying this
        # same event wrong), so Stripe's own redelivery schedule is what
        # drives the next attempt, by which point this event will be
        # reapplied against the row's now-current state.
        db.rollback()
        logger.warning(
            "receive_stripe_webhook: version conflict applying event provider=%s event_id=%s: %s",
            event.provider_name,
            event.event_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "subscription_version_conflict", "message": str(exc)},
        ) from exc
    except IntegrityError:
        # A genuinely concurrent delivery of the SAME event won the race
        # to commit its own (identical) receipt row first -- our own
        # pending receipt insert collided with the UNIQUE(provider_name,
        # event_id) constraint at commit time. The winner's mutation
        # already applied; nothing further to do here.
        db.rollback()
        logger.info(
            "receive_stripe_webhook: concurrent duplicate delivery raced us, "
            "provider=%s event_id=%s",
            event.provider_name,
            event.event_id,
        )
        return {"status": "already_processed"}

    return {"status": "processed"}
