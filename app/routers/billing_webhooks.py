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
from app.billing.service import BillingService
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

    try:
        BillingService(db, provider=provider).sync_from_webhook_event(event)
    except (LookupError, ValueError) as exc:
        # A structurally unresolvable event (unknown organization/plan/
        # provider_reference) -- never recorded as processed, so a
        # legitimate redelivery (e.g. after we fix a data issue) can
        # still be retried. Stripe will retry a non-2xx response on its
        # own schedule.
        logger.error(
            "receive_stripe_webhook: could not apply event provider=%s event_id=%s error=%s",
            event.provider_name,
            event.event_id,
            exc,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    receipt = ProviderWebhookReceipt(provider_name=event.provider_name, event_id=event.event_id)
    db.add(receipt)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent delivery of the same event raced us here -- the
        # mutation above already succeeded (BillingService's own methods
        # are each idempotent in their effect, e.g. re-canceling an
        # already-canceled subscription is a no-op), and the other
        # request's receipt row already exists; nothing further to do.
        db.rollback()

    return {"status": "processed"}
