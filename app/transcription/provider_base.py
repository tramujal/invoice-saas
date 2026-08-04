"""Provider-agnostic voice-transcription interface (Phase 23, for the
experimental WhatsApp assistant's voice-note support).

Mirrors app/ai/base.py's AIProvider and app/email/base.py's EmailSender
exactly: callers (app.whatsapp.service) depend only on
TranscriptionProvider/TranscriptionError/TranscriptionNotConfiguredError,
never on a concrete vendor SDK. Swapping or adding a real provider means
writing one new class here and adding one branch in
app/transcription/factory.py -- nothing else in the app changes.
"""

from abc import ABC, abstractmethod


class TranscriptionError(Exception):
    """Raised when the underlying provider fails to transcribe audio for
    any reason other than "not configured at all" (see
    TranscriptionNotConfiguredError below) -- a malformed file, a vendor
    outage, an unsupported format the provider itself rejects."""


class TranscriptionNotConfiguredError(TranscriptionError):
    """Raised when no real transcription provider is configured. The
    WhatsApp voice-note flow must show an honest "voice transcription
    isn't set up" message rather than pretending the audio was
    understood -- see docs/whatsapp.md's "Voice messages" section."""


class TranscriptionProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        """Returns the transcribed text for one audio clip. Implementations
        never persist the raw audio themselves -- see
        app.whatsapp.service's own temporary-file handling, which deletes
        the audio immediately after this call returns (success or
        failure)."""
        raise NotImplementedError
