"""The inbound endpoint the Node whatsapp-bridge service calls for every
normalized message it receives (see whatsapp-bridge/src/transport/
backend-client.ts). NOT user-authenticated -- there is no browser session
or JWT here, by construction: the bridge is a separate process the same
operator runs, authenticated purely via the shared HMAC secret (mirrors
app.routers.billing_webhooks's Stripe-webhook pattern exactly: raw body
read, signature verified before any JSON parsing, replay-protected via a
timestamp tolerance window).

This router does no business-logic interpretation itself -- it verifies
the request, parses the envelope, and hands off to
app.whatsapp.service.handle_inbound_message, which re-derives the entire
authorization chain (see that module's own docstring).
"""

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.whatsapp.config import WHATSAPP_SIGNATURE_TOLERANCE_SECONDS
from app.whatsapp.schemas import WhatsAppInboundEnvelope
from app.whatsapp.security import InvalidBridgeSignatureError, SIGNATURE_HEADER, verify_bridge_signature
from app.whatsapp.service import handle_inbound_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp/bridge", tags=["whatsapp"])

# Request-body size cap, enforced BEFORE signature verification (a huge
# body is rejected cheaply, never HMAC'd first) -- mirrors this app's
# other explicit size limits (e.g. IMPORT_MAX_FILE_SIZE_BYTES).
_MAX_INBOUND_BODY_BYTES = 8 * 1024 * 1024  # 8 MB, generous for a base64 voice note + JSON envelope


def _get_bridge_secret() -> str:
    secret = os.environ.get("WHATSAPP_BRIDGE_SECRET", "").strip()
    if not secret:
        # The bridge itself is unconfigured/disabled -- never a 500;
        # exactly the "must not accept unsigned requests just because no
        # secret happens to be set" failure-closed behavior.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "whatsapp_not_configured", "message": "The WhatsApp bridge is not configured."},
        )
    return secret


@router.post("/inbound", status_code=status.HTTP_200_OK)
async def receive_inbound_whatsapp_message(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    body = await request.body()
    if len(body) > _MAX_INBOUND_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "request_too_large", "message": "Request body exceeds the maximum allowed size."},
        )

    secret = _get_bridge_secret()
    signature_header = request.headers.get(SIGNATURE_HEADER.lower(), "")
    try:
        verify_bridge_signature(
            secret=secret,
            signature_header=signature_header,
            body=body,
            tolerance_seconds=WHATSAPP_SIGNATURE_TOLERANCE_SECONDS,
        )
    except InvalidBridgeSignatureError:
        # Never distinguishes "missing header" from "bad timestamp" from
        # "bad signature" in the response -- same sanitized-error
        # requirement as every other signature verifier in this app.
        logger.warning("whatsapp_bridge: rejected inbound request with invalid signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_signature", "message": "Invalid or missing bridge signature."},
        )

    try:
        payload = json.loads(body)
        envelope = WhatsAppInboundEnvelope.model_validate(payload)
    except (ValidationError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_envelope", "message": "Malformed inbound message envelope."},
        )

    return handle_inbound_message(db, envelope)
