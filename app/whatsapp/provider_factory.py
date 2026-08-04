"""Resolves the configured WhatsAppProvider -- mirrors
app.ai.factory.get_ai_provider's exact shape: called explicitly (never a
FastAPI Depends), "optional infrastructure" contract, WHATSAPP_ENABLED
checked first as the one shared kill-switch every caller goes through.
"""

import os

from app.whatsapp.bridge_provider import bridge_provider_from_env
from app.whatsapp.null_provider import NullWhatsAppProvider
from app.whatsapp.provider_base import WhatsAppNotConfiguredError, WhatsAppProvider

_DEFAULT_PROVIDER = "null"


def is_whatsapp_transport_enabled() -> bool:
    """WHATSAPP_ENABLED, parsed the same permissive way this codebase
    already parses boolean env flags elsewhere -- "true"/"1"/"yes"
    (case-insensitive), everything else is false. Deliberately defaults to
    false: the app must start and function normally with WhatsApp
    disabled, per this phase's own explicit requirement."""
    return os.environ.get("WHATSAPP_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def is_whatsapp_transport_configured() -> bool:
    """Cheap check for whether get_whatsapp_provider() would currently
    return a real (bridge) provider rather than Null -- used by the
    Settings -> WhatsApp status page to distinguish "disabled" from
    "enabled but unconfigured" without constructing a provider."""
    if not is_whatsapp_transport_enabled():
        return False
    provider_name = (os.environ.get("WHATSAPP_PROVIDER") or _DEFAULT_PROVIDER).strip().lower()
    if provider_name != "bridge":
        return False
    return bool(os.environ.get("WHATSAPP_BRIDGE_URL", "").strip()) and bool(
        os.environ.get("WHATSAPP_BRIDGE_SECRET", "").strip()
    )


def get_whatsapp_provider() -> WhatsAppProvider:
    """WHATSAPP_ENABLED=false (the default) or an unrecognized/unset
    WHATSAPP_PROVIDER both resolve to NullWhatsAppProvider -- a safe,
    always-constructible no-op, never a raised error, since the app must
    keep functioning normally with WhatsApp off. Only WHATSAPP_PROVIDER
    =bridge with WHATSAPP_ENABLED=true attempts to build a real
    BridgeWhatsAppProvider, which itself raises WhatsAppNotConfiguredError
    if the bridge URL/secret are missing -- that error is intentionally
    NOT swallowed here, so a caller that specifically needs to distinguish
    "disabled" from "enabled but misconfigured" (the Settings page) can
    still do so by calling is_whatsapp_transport_configured() first."""
    if not is_whatsapp_transport_enabled():
        return NullWhatsAppProvider()

    provider_name = (os.environ.get("WHATSAPP_PROVIDER") or _DEFAULT_PROVIDER).strip().lower()
    if provider_name != "bridge":
        return NullWhatsAppProvider()

    try:
        return bridge_provider_from_env()
    except WhatsAppNotConfiguredError:
        return NullWhatsAppProvider()
