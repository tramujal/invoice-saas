from app.transcription.provider_base import TranscriptionNotConfiguredError, TranscriptionProvider


class NullTranscriptionProvider(TranscriptionProvider):
    """The safe default when no real transcription vendor is configured
    (TRANSCRIPTION_PROVIDER unset or "null") -- every call raises
    TranscriptionNotConfiguredError instead of silently pretending to
    understand audio it never processed. app.whatsapp.service catches
    this specifically to send an honest "voice transcription isn't
    configured yet" reply rather than a generic error."""

    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        raise TranscriptionNotConfiguredError(
            "No transcription provider is configured (TRANSCRIPTION_PROVIDER=null)."
        )
