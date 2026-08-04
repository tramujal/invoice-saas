"""The real WhatsAppProvider implementation: an HTTP client for the
separate Node "whatsapp-bridge" service (see whatsapp-bridge/README.md).
This is the ONLY module in the Python codebase that knows the bridge's
HTTP contract -- app.whatsapp.service and every router talk to
WhatsAppProvider only (see provider_base.py).

Every request is signed (app.whatsapp.security.sign_bridge_request) so the
bridge can verify it actually came from this backend, not an arbitrary
caller who found the bridge's port -- the bridge is a plain HTTP service
with no authentication of its own beyond this shared secret. Every
request has an explicit timeout (WHATSAPP_REQUEST_TIMEOUT_SECONDS); a
hung or unreachable bridge must never hang a FastAPI worker thread
indefinitely (see docs/whatsapp.md's "Bridge reliability" section: the
SaaS must remain operational when the bridge is down).
"""

import base64
import logging
import os
import time

import requests

from app.whatsapp.provider_base import (
    WhatsAppBridgeUnavailableError,
    WhatsAppConnectionState,
    WhatsAppConnectionStatus,
    WhatsAppNotConfiguredError,
    WhatsAppProvider,
    WhatsAppProviderError,
    WhatsAppQrCode,
)
from app.whatsapp.security import sign_bridge_request

logger = logging.getLogger(__name__)

_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0


class BridgeWhatsAppProvider(WhatsAppProvider):
    def __init__(self, *, bridge_url: str, bridge_secret: str, timeout_seconds: float) -> None:
        self._bridge_url = bridge_url.rstrip("/")
        self._bridge_secret = bridge_secret
        self._timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        import json as json_module

        body = json_module.dumps(json_body or {}).encode("utf-8")
        timestamp = int(time.time())
        signature = sign_bridge_request(secret=self._bridge_secret, timestamp=timestamp, body=body)
        try:
            response = requests.request(
                method,
                f"{self._bridge_url}{path}",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-WhatsApp-Bridge-Signature": signature,
                },
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            # Never includes the bridge secret or the raw exception's
            # str() (which can embed the target URL/host) in a message
            # that might reach a user-facing surface -- callers only ever
            # see this exception's type, never str(exc), past this point.
            logger.warning("whatsapp_bridge: request failed method=%s path=%s", method, path)
            raise WhatsAppBridgeUnavailableError("The WhatsApp bridge is unreachable.") from exc

        if response.status_code >= 500:
            raise WhatsAppBridgeUnavailableError("The WhatsApp bridge returned a server error.")
        if response.status_code >= 400:
            raise WhatsAppProviderError(f"The WhatsApp bridge rejected the request ({response.status_code}).")

        try:
            return response.json()
        except ValueError as exc:
            raise WhatsAppProviderError("The WhatsApp bridge returned a malformed response.") from exc

    def get_connection_status(self) -> WhatsAppConnectionStatus:
        data = self._request("GET", "/status")
        try:
            state = WhatsAppConnectionState(data.get("state", "disconnected"))
        except ValueError:
            state = WhatsAppConnectionState.disconnected
        return WhatsAppConnectionStatus(
            state=state,
            connected_phone_number=data.get("connected_phone_number"),
            last_heartbeat_at=data.get("last_heartbeat_at"),
        )

    def request_qr_code(self) -> WhatsAppQrCode:
        data = self._request("POST", "/qr")
        return WhatsAppQrCode(qr_data_base64=data["qr_data_base64"], expires_at=data["expires_at"])

    def send_text_message(self, phone_number: str, text: str) -> None:
        self._request("POST", "/send/text", json_body={"phone_number": phone_number, "text": text})

    def send_document(self, phone_number: str, filename: str, content: bytes, mime_type: str) -> None:
        self._request(
            "POST",
            "/send/document",
            json_body={
                "phone_number": phone_number,
                "filename": filename,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "mime_type": mime_type,
            },
        )

    def reconnect(self) -> None:
        self._request("POST", "/reconnect")

    def disconnect(self) -> None:
        self._request("POST", "/disconnect")

    def delete_session(self) -> None:
        self._request("POST", "/session/delete")


def bridge_provider_from_env() -> BridgeWhatsAppProvider:
    """Constructs a BridgeWhatsAppProvider from WHATSAPP_BRIDGE_URL/
    WHATSAPP_BRIDGE_SECRET/WHATSAPP_REQUEST_TIMEOUT_SECONDS -- raises
    WhatsAppNotConfiguredError if either required value is missing,
    exactly like app.ai.factory.get_ai_provider's missing-API-key case."""
    bridge_url = os.environ.get("WHATSAPP_BRIDGE_URL", "").strip()
    bridge_secret = os.environ.get("WHATSAPP_BRIDGE_SECRET", "").strip()
    if not bridge_url or not bridge_secret:
        raise WhatsAppNotConfiguredError(
            "WHATSAPP_BRIDGE_URL and WHATSAPP_BRIDGE_SECRET must both be set to use the bridge provider."
        )
    timeout_seconds = float(os.environ.get("WHATSAPP_REQUEST_TIMEOUT_SECONDS", str(_DEFAULT_REQUEST_TIMEOUT_SECONDS)))
    return BridgeWhatsAppProvider(bridge_url=bridge_url, bridge_secret=bridge_secret, timeout_seconds=timeout_seconds)
