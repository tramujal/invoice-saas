from app.transcription.provider_base import TranscriptionError, TranscriptionProvider


class FakeTranscriptionProvider(TranscriptionProvider):
    """Test/demo-only provider: returns a pre-scripted transcript (or
    raises a pre-scripted error) instead of calling a real vendor.
    TRANSCRIPTION_PROVIDER=fake is intended for controlled manual demos
    of the voice-note flow without a real speech-to-text API key -- see
    docs/whatsapp.md. Never selectable in a production environment (see
    app.transcription.factory.get_transcription_provider)."""

    def __init__(self, transcript: str = "", error: Exception | None = None) -> None:
        self.transcript = transcript
        self.error = error
        self.calls: list[tuple[bytes, str]] = []

    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        self.calls.append((audio_bytes, mime_type))
        if self.error is not None:
            raise self.error
        if not self.transcript:
            raise TranscriptionError("FakeTranscriptionProvider has no scripted transcript configured.")
        return self.transcript
