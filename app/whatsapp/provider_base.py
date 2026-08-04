"""Provider-agnostic WhatsApp transport interface (Phase 23 -- the
experimental WhatsApp assistant).

Mirrors app/ai/base.py's AIProvider and app/email/base.py's EmailSender
exactly: app.whatsapp.service depends only on
WhatsAppProvider/WhatsAppQrCode/WhatsAppConnectionStatus/the typed
errors below, never on whatsapp-web.js-specific objects (a Puppeteer
page handle, a raw wwebjs Client, a Baileys socket, ...). Nothing outside
app/whatsapp/bridge_provider.py ever sees anything provider-specific.

IMPORTANT ARCHITECTURAL NOTE (documented here since it shapes every
caller of this interface): this experimental phase runs exactly ONE
shared WhatsApp Web session for the WHOLE deployment, not one per
organization. WHATSAPP_BRIDGE_URL/WHATSAPP_BRIDGE_SECRET are singular,
global settings (see .env.example) -- there is one physical phone number
connected via QR, used across every organization that has WhatsApp
enabled on its plan. Per-organization scoping is enforced entirely
through WhatsAppIdentity (phone -> org+user), not through separate bridge
processes. A future iteration could run one bridge per organization; this
MVP deliberately does not, matching the "enable only on Enterprise or an
internal demo plan" framing in the phase's own spec -- see
docs/whatsapp.md for the full rationale. Connecting/disconnecting/
requesting a new QR from ANY organization's Settings -> WhatsApp page
affects this one shared session for every organization, which is exactly
why those controls require settings.manage and are clearly labeled
experimental in the UI.

The future Meta Cloud API (an official, per-organization-token-based
transport) fits behind this exact same interface -- see docs/whatsapp.md's
"Migration path to Meta Cloud API" section for what would change (a new
CloudApiWhatsAppProvider implementing this ABC) and what would not (every
caller of WhatsAppProvider, all of app.whatsapp.service, every router).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class WhatsAppConnectionState(str, Enum):
    disconnected = "disconnected"
    qr_required = "qr_required"
    connecting = "connecting"
    connected = "connected"
    session_expired = "session_expired"


@dataclass(frozen=True)
class WhatsAppConnectionStatus:
    state: WhatsAppConnectionState
    # Masked/partial when connected (e.g. "+598 99 ***  456") -- the
    # bridge never sends, and this app never stores, the full connected
    # number outside WhatsAppIdentity rows, which are already
    # organization-scoped and permission-gated.
    connected_phone_number: str | None
    last_heartbeat_at: str | None  # ISO 8601, or None if never connected


@dataclass(frozen=True)
class WhatsAppQrCode:
    # Base64-encoded PNG, ready for an <img src="data:image/png;base64,...">
    # -- never a raw session credential, just a scannable login QR that
    # expires on its own (see expires_at) same as WhatsApp Web's own UI.
    qr_data_base64: str
    expires_at: str  # ISO 8601


class WhatsAppProviderError(Exception):
    """Raised when the underlying transport fails for any reason other
    than "not configured" (see WhatsAppNotConfiguredError) -- a bridge
    HTTP error, a malformed bridge response, an unreachable bridge."""


class WhatsAppNotConfiguredError(WhatsAppProviderError):
    """Raised when WHATSAPP_ENABLED is false, or the selected provider is
    missing required configuration (e.g. WHATSAPP_BRIDGE_URL/
    WHATSAPP_BRIDGE_SECRET for the bridge provider). Distinct from a
    connection-state problem (see WhatsAppConnectionState.disconnected) --
    "the transport isn't even configured" is a different, calmer failure
    mode than "it's configured but not currently connected," and
    app.whatsapp.service surfaces the two differently (see
    docs/whatsapp.md's "Plans and quotas" section on why the app
    distinguishes disabled transport / unconfigured transport / plan
    restriction as three separate states)."""


class WhatsAppBridgeUnavailableError(WhatsAppProviderError):
    """Raised specifically when the bridge process itself can't be
    reached (connection refused/timeout) -- as opposed to the bridge
    responding with an application-level error. Lets callers distinguish
    "the bridge is down" from "the bridge said no" without inspecting
    exception text."""


class WhatsAppProvider(ABC):
    @abstractmethod
    def get_connection_status(self) -> WhatsAppConnectionStatus:
        raise NotImplementedError

    @abstractmethod
    def request_qr_code(self) -> WhatsAppQrCode:
        """Requests a fresh QR code for linking the shared WhatsApp Web
        session. Only meaningful when the connection state is
        disconnected/qr_required/session_expired -- callers check
        get_connection_status() first."""
        raise NotImplementedError

    @abstractmethod
    def send_text_message(self, phone_number: str, text: str) -> None:
        """`phone_number` must already be normalized (see
        app.whatsapp.security.normalize_phone_number) -- this method never
        normalizes or validates a phone number itself."""
        raise NotImplementedError

    @abstractmethod
    def send_document(
        self, phone_number: str, filename: str, content: bytes, mime_type: str
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def reconnect(self) -> None:
        """Requests the bridge tear down and re-establish its WhatsApp
        Web connection (e.g. after session_expired). Does not itself wait
        for the reconnection to complete -- callers poll
        get_connection_status()."""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Logs out of WhatsApp Web but keeps no session data around for
        an automatic reconnect -- distinct from delete_session() only in
        that a provider MAY choose to keep non-credential bookkeeping
        (e.g. its own internal reconnect-backoff state); no session
        credential may survive either call."""
        raise NotImplementedError

    @abstractmethod
    def delete_session(self) -> None:
        """Explicit, irreversible removal of the persisted WhatsApp Web
        session (see docs/whatsapp.md's "Session persistence" section) --
        the next connection attempt always starts from a fresh QR scan.
        Never automatic; only ever triggered by an explicit
        settings.manage action."""
        raise NotImplementedError
