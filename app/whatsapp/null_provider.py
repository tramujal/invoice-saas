from app.whatsapp.provider_base import (
    WhatsAppConnectionState,
    WhatsAppConnectionStatus,
    WhatsAppNotConfiguredError,
    WhatsAppProvider,
)


class NullWhatsAppProvider(WhatsAppProvider):
    """The safe default when WHATSAPP_ENABLED is false or WHATSAPP_PROVIDER
    is unset/"null" -- the app must start and function normally in this
    state (per the phase's own explicit requirement). Every mutating
    method raises WhatsAppNotConfiguredError; get_connection_status()
    returns `disconnected` rather than raising, so a status-display caller
    (the Settings -> WhatsApp page) can render a calm "not enabled" state
    without a try/except."""

    def get_connection_status(self) -> WhatsAppConnectionStatus:
        return WhatsAppConnectionStatus(
            state=WhatsAppConnectionState.disconnected,
            connected_phone_number=None,
            last_heartbeat_at=None,
        )

    def request_qr_code(self):
        raise WhatsAppNotConfiguredError("WhatsApp is disabled or unconfigured.")

    def send_text_message(self, phone_number: str, text: str) -> None:
        raise WhatsAppNotConfiguredError("WhatsApp is disabled or unconfigured.")

    def send_document(self, phone_number: str, filename: str, content: bytes, mime_type: str) -> None:
        raise WhatsAppNotConfiguredError("WhatsApp is disabled or unconfigured.")

    def reconnect(self) -> None:
        raise WhatsAppNotConfiguredError("WhatsApp is disabled or unconfigured.")

    def disconnect(self) -> None:
        raise WhatsAppNotConfiguredError("WhatsApp is disabled or unconfigured.")

    def delete_session(self) -> None:
        raise WhatsAppNotConfiguredError("WhatsApp is disabled or unconfigured.")
