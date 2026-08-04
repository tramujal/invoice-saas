"""Resolves the configured TranscriptionProvider from the
TRANSCRIPTION_PROVIDER env var -- mirrors app.ai.factory.get_ai_provider's
exact shape (explicit function call, not a FastAPI Depends, so cheaper
checks run first; "optional infrastructure" contract, never a boot-time
requirement).

No real transcription vendor is wired up in this experimental phase: this
app's only existing AI provider integrations (Anthropic, Gemini, see
app/ai/) are built around app.ai.base.AIProvider's text-message-in/
text-or-tool-call-out contract, which has no audio-input concept at all --
bolting audio transcription onto that interface would mean widening the
domain-critical AIProvider contract itself just for this one experimental
feature, not "reusing an existing provider cleanly." Per this phase's own
instructions ("add one configurable real adapter only if an existing
provider/API can support it cleanly"), that bar isn't met today, so only
Null and Fake providers exist -- see docs/whatsapp.md's "Voice messages"
section for the honest state of this and the migration path if a real
speech-to-text vendor is added later behind this same interface.
"""

import os

from app.security import ENVIRONMENT
from app.transcription.fake_provider import FakeTranscriptionProvider
from app.transcription.null_provider import NullTranscriptionProvider
from app.transcription.provider_base import TranscriptionProvider

_DEFAULT_PROVIDER = "null"


def is_transcription_configured() -> bool:
    """Cheap check for whether a real (non-null) transcription provider is
    selected -- used by the Settings -> WhatsApp status page to show
    "voice notes unconfigured" distinctly from "voice notes disabled by
    plan" without constructing a provider."""
    provider_name = (os.environ.get("TRANSCRIPTION_PROVIDER") or _DEFAULT_PROVIDER).strip().lower()
    return provider_name == "fake" or provider_name not in ("null", "")


def get_transcription_provider() -> TranscriptionProvider:
    provider_name = (os.environ.get("TRANSCRIPTION_PROVIDER") or _DEFAULT_PROVIDER).strip().lower()

    if provider_name == "fake":
        # Never selectable in production -- a demo-only knob for manually
        # exercising the voice-note flow without a real speech-to-text
        # vendor. Falls back to Null exactly as an unrecognized provider
        # name would, rather than ever pretending to transcribe in prod.
        if ENVIRONMENT == "production":
            return NullTranscriptionProvider()
        return FakeTranscriptionProvider(transcript=os.environ.get("TRANSCRIPTION_FAKE_TRANSCRIPT", ""))

    # "null", empty, or anything unrecognized -- fails closed to the safe
    # no-op provider, never silently to a real one.
    return NullTranscriptionProvider()
