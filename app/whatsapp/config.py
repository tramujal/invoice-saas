"""All experimental-WhatsApp-assistant numeric/behavioral knobs, centralized
and env-configurable, with conservative defaults -- mirrors app/ai/limits.py's
exact convention (read once at import time, one place that defines "how big
is too big" for this feature).
"""

import os

WHATSAPP_MESSAGE_MAX_LENGTH = int(os.environ.get("WHATSAPP_MESSAGE_MAX_LENGTH", "1000"))

# WhatsApp's own common voice-note format is Opus-in-Ogg ("audio/ogg;
# codecs=opus"); some clients send audio/mpeg or audio/aac. Kept as a
# closed allow-list -- an unrecognized MIME type is rejected outright,
# never guessed at or passed through to a transcription provider blind.
WHATSAPP_ALLOWED_AUDIO_MIME_TYPES = frozenset(
    {"audio/ogg", "audio/ogg; codecs=opus", "audio/mpeg", "audio/mp4", "audio/aac", "audio/amr"}
)
WHATSAPP_AUDIO_MAX_BYTES = int(os.environ.get("WHATSAPP_AUDIO_MAX_BYTES", str(5 * 1024 * 1024)))  # 5 MB
WHATSAPP_AUDIO_MAX_SECONDS = int(os.environ.get("WHATSAPP_AUDIO_MAX_SECONDS", "120"))

WHATSAPP_CONTEXT_TTL_MINUTES = int(os.environ.get("WHATSAPP_CONTEXT_TTL_MINUTES", "15"))
WHATSAPP_CONTEXT_MAX_MESSAGES = int(os.environ.get("WHATSAPP_CONTEXT_MAX_MESSAGES", "10"))

# Documented, not actually a toggle: this app never supports disabling
# confirmation for mutating WhatsApp commands (see docs/whatsapp.md's
# security model -- "Do NOT weaken ... confirmations" is a hard
# requirement of this phase, not a configurable preference). Read at
# startup only so a misconfigured "false" is visible in logs rather than
# silently ignored.
WHATSAPP_REQUIRE_CONFIRMATION = os.environ.get("WHATSAPP_REQUIRE_CONFIRMATION", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)

WHATSAPP_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("WHATSAPP_REQUEST_TIMEOUT_SECONDS", "10"))
WHATSAPP_SIGNATURE_TOLERANCE_SECONDS = int(os.environ.get("WHATSAPP_SIGNATURE_TOLERANCE_SECONDS", "300"))

# Linking-code lifecycle (Phase 23 section 5).
WHATSAPP_VERIFICATION_CODE_TTL_MINUTES = int(os.environ.get("WHATSAPP_VERIFICATION_CODE_TTL_MINUTES", "10"))
WHATSAPP_MAX_VERIFICATION_ATTEMPTS = int(os.environ.get("WHATSAPP_MAX_VERIFICATION_ATTEMPTS", "5"))
