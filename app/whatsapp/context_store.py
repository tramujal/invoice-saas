"""In-process, short-lived conversation context for the WhatsApp channel
(Phase 23, spec section 10).

Deliberately in-memory, not a database table -- this app already runs as
a single process (see app.rate_limit's own module docstring for the same
"single Render web service, no Redis" reasoning this mirrors), and
keeping conversation content out of the database entirely is a stronger
form of "minimal retention" than a TTL'd DB row would be: a process
restart discards every pending context outright, and nothing here is ever
written to disk. The tradeoff -- context is lost on a deploy/restart -- is
explicitly acceptable for an experimental feature (see docs/whatsapp.md).

Scoped by (organization_id, user_id) -- never by phone number alone, and
never shared across users or organizations, so there is no cross-tenant
or cross-user leakage path through this store even if two different
phones were (hypothetically) ever linked to accounts that share a process.
"""

import threading
import time
from dataclasses import dataclass, field

_DEFAULT_TTL_MINUTES = 15
_DEFAULT_MAX_MESSAGES = 10


@dataclass
class WhatsAppTurnMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class WhatsAppConversationContext:
    messages: list[WhatsAppTurnMessage] = field(default_factory=list)
    # Set when the assistant just proposed a mutating action -- CONFIRMAR/
    # CANCELAR act on this id. Cleared the moment it's confirmed, cancelled,
    # or superseded by a new proposal.
    pending_proposal_id: str | None = None
    last_touched_at: float = field(default_factory=time.monotonic)


class WhatsAppContextStore:
    """Thread-safe, TTL'd, size-bounded store -- same "plain dict guarded
    by a lock, swept probabilistically" shape as
    app.rate_limit.InMemoryRateLimiterBackend, for the same reason (this
    process is the only place this state needs to live)."""

    def __init__(self, *, ttl_minutes: int = _DEFAULT_TTL_MINUTES, max_messages: int = _DEFAULT_MAX_MESSAGES) -> None:
        self._ttl_seconds = ttl_minutes * 60
        self._max_messages = max_messages
        self._lock = threading.Lock()
        self._contexts: dict[tuple[str, str], WhatsAppConversationContext] = {}

    def _key(self, organization_id: str, user_id: str) -> tuple[str, str]:
        return (organization_id, user_id)

    def _is_expired(self, context: WhatsAppConversationContext) -> bool:
        return time.monotonic() - context.last_touched_at >= self._ttl_seconds

    def get(self, organization_id: str, user_id: str) -> WhatsAppConversationContext:
        """Always returns a usable context -- a missing or expired one is
        silently treated as fresh, never an error (forgetting context is
        never a failure mode for the caller)."""
        with self._lock:
            key = self._key(organization_id, user_id)
            context = self._contexts.get(key)
            if context is None or self._is_expired(context):
                context = WhatsAppConversationContext()
                self._contexts[key] = context
            return context

    def append_turn(self, organization_id: str, user_id: str, role: str, content: str) -> None:
        with self._lock:
            key = self._key(organization_id, user_id)
            context = self._contexts.get(key)
            if context is None or self._is_expired(context):
                context = WhatsAppConversationContext()
                self._contexts[key] = context
            context.messages.append(WhatsAppTurnMessage(role=role, content=content))
            # Keep only the most recent N messages -- context never grows
            # unbounded within its own TTL window.
            if len(context.messages) > self._max_messages:
                context.messages = context.messages[-self._max_messages :]
            context.last_touched_at = time.monotonic()

    def set_pending_proposal(self, organization_id: str, user_id: str, proposal_id: str | None) -> None:
        with self._lock:
            key = self._key(organization_id, user_id)
            context = self._contexts.get(key)
            if context is None or self._is_expired(context):
                context = WhatsAppConversationContext()
                self._contexts[key] = context
            context.pending_proposal_id = proposal_id
            context.last_touched_at = time.monotonic()

    def forget(self, organization_id: str, user_id: str) -> None:
        """The explicit "olvidar contexto" command -- and also called on
        logout-equivalent events (identity revoked)."""
        with self._lock:
            self._contexts.pop(self._key(organization_id, user_id), None)

    def sweep_expired(self) -> int:
        """Removes every expired context -- the cleanup job (Phase 23
        section 18) calls this periodically; also swept opportunistically
        with low probability on normal access, mirroring
        InMemoryRateLimiterBackend's own _maybe_sweep. Returns the number
        of contexts removed (surfaced in the job's result_summary)."""
        with self._lock:
            expired_keys = [key for key, context in self._contexts.items() if self._is_expired(context)]
            for key in expired_keys:
                del self._contexts[key]
            return len(expired_keys)


# One process-wide store -- mirrors app.rate_limit's single module-level
# `_backend` instance exactly.
_store = WhatsAppContextStore()


def get_context_store() -> WhatsAppContextStore:
    return _store
