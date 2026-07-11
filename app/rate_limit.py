"""Server-side rate limiting: brute-force / abuse / flood protection for
sensitive auth and business-action endpoints.

Storage
-------
A single in-process, thread-safe, fixed-window counter store
(InMemoryRateLimiterBackend) is sufficient today: this app runs as one
Render "free" web service — a single process, no other instance to
coordinate with, and no Redis or other shared cache already exists
anywhere in this stack. Fixed-window counters (rather than a sliding log)
are deliberately simple: enough to stop brute-force/spam at this scale,
without the extra memory a more precise sliding window would cost for no
real benefit here.

Upgrading to Redis later only requires writing a class that implements
RateLimiterBackend.hit() against Redis (e.g. INCR + EXPIRE per bucket key,
or a sorted-set sliding window) and changing the single line below that
constructs `_backend`. No route, call site, or response shape changes.

Trusted proxy / client IP
--------------------------
This app is deployed on Render, behind exactly one reverse proxy hop. That
proxy *appends* the real peer IP as the LAST entry of X-Forwarded-For
(standard nginx-style `$proxy_add_x_forwarded_for` behavior: each hop
appends to whatever X-Forwarded-For it already received — it never
replaces it). That means everything before the last trusted hop's entry
can be freely set by the client itself and must never be trusted blindly;
only trusting the leftmost entry (a common mistake) would let any caller
evade IP-based limits just by sending their own fake X-Forwarded-For.

TRUSTED_PROXY_HOPS (env var, default "0") is the number of trusted reverse
proxies known to sit in front of this app:
  - 0 (default — local dev, tests, or any deployment with no configured
    proxy): X-Forwarded-For is ignored entirely; request.client.host (the
    real TCP peer) is used.
  - 1 (set in render.yaml for the deployed service): the LAST entry of
    X-Forwarded-For is trusted as the real client IP — it was appended by
    Render's own edge proxy, which saw the true peer directly. Everything
    before that entry is attacker-controllable and ignored.
This makes spoofing X-Forwarded-For a no-op against any deployment that
hasn't explicitly configured a trusted hop count (falls back to the real
socket peer), while still correctly extracting the real client from behind
Render's one known proxy hop in production.

IMPORTANT — uvicorn has its own, separate proxy-header trust that must be
disabled: uvicorn's ProxyHeadersMiddleware is enabled by default and, by
default, trusts X-Forwarded-For (rewriting the ASGI scope's `client` — i.e.
what `request.client.host` returns) for any connection whose direct TCP
peer is 127.0.0.1. That happens *before* this module ever sees the
request, entirely independent of TRUSTED_PROXY_HOPS above — so without
disabling it, anyone connecting over loopback (trivially true for the
common case of a proxy/sidecar on the same host, or simply a local dev
server) could spoof X-Forwarded-For and have uvicorn itself rewrite
`request.client.host`, silently defeating the "TRUSTED_PROXY_HOPS=0 means
ignore X-Forwarded-For" default this module relies on. Both the local dev
launch config (.claude/launch.json) and render.yaml's startCommand pass
`--forwarded-allow-ips=""` for exactly this reason, making this module's
own TRUSTED_PROXY_HOPS check the *only* place X-Forwarded-For is ever
interpreted.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

RATE_LIMIT_CODE = "rate_limit_exceeded"
RATE_LIMIT_MESSAGE = "Too many requests. Please try again later."


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitCheck:
    """One bucket to evaluate: every rule in `rules` is checked against the
    same `identity` under `scope` — e.g. login's IP check has two rules
    (5/min and 20/hour) evaluated against the same "ip:1.2.3.4" identity."""

    scope: str
    identity: str
    rules: tuple[RateLimitRule, ...]


class RateLimiterBackend(Protocol):
    def hit(self, bucket_key: str, window_seconds: int, limit: int) -> tuple[bool, int]:
        """Records one hit against bucket_key and returns (allowed,
        retry_after_seconds). retry_after_seconds is only meaningful when
        allowed is False."""
        ...


class InMemoryRateLimiterBackend:
    """Fixed-window counters in a plain dict, guarded by a lock — FastAPI
    runs sync route handlers in a thread pool, so concurrent requests can
    call `hit` from different threads at once.

    Each bucket resets itself the first time it's hit after its window has
    elapsed; no separate timer/thread is needed. To keep memory bounded on
    a long-running process, every call has a small chance of sweeping out
    buckets whose window ended a while ago.
    """

    _SWEEP_PROBABILITY = 0.01
    _SWEEP_STALE_AFTER_SECONDS = 3600

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, int]] = {}

    def hit(self, bucket_key: str, window_seconds: int, limit: int) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            window_start, count = self._buckets.get(bucket_key, (now, 0))
            if now - window_start >= window_seconds:
                window_start, count = now, 0
            count += 1
            self._buckets[bucket_key] = (window_start, count)
            self._maybe_sweep(now)
            if count > limit:
                retry_after = max(1, int(window_seconds - (now - window_start)))
                return False, retry_after
            return True, 0

    def _maybe_sweep(self, now: float) -> None:
        # Caller already holds self._lock.
        if random.random() > self._SWEEP_PROBABILITY:
            return
        stale = [
            key
            for key, (start, _count) in self._buckets.items()
            if now - start >= self._SWEEP_STALE_AFTER_SECONDS
        ]
        for key in stale:
            del self._buckets[key]


# The one line a future Redis-backed implementation needs to replace.
_backend: RateLimiterBackend = InMemoryRateLimiterBackend()


def _normalize_ip(raw: str | None) -> str | None:
    """Validates and canonicalizes a candidate IP address. Returns None for
    anything that isn't a syntactically valid IP — callers must treat that
    as "untrusted, fall back", never as "trust it anyway"."""
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return None


def get_client_ip(request: Request) -> str:
    """Returns the best-trusted client IP — see the module docstring for
    the full trust model. Never trusts X-Forwarded-For unless
    TRUSTED_PROXY_HOPS says a proxy in front of us is expected to have set
    it, and even then only trusts the entry that proxy hop itself appended."""
    hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
    if hops > 0:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            hop_ips = [part.strip() for part in xff.split(",") if part.strip()]
            if len(hop_ips) >= hops:
                candidate = _normalize_ip(hop_ips[-hops])
                if candidate:
                    return candidate

    direct = request.client.host if request.client else None
    return _normalize_ip(direct) or "unknown"


def hash_identifier(value: str) -> str:
    """Non-reversible identifier for values that must never appear in a
    rate-limit bucket key (or log line) in raw form — e.g. a login email."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_log_identity(identity: str) -> str:
    """Never logs a raw IP, user id, or email hash in full — only a short,
    stable, non-reversible fingerprint, enough to correlate repeated
    events across log lines without exposing any identifying value."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def enforce_rate_limit(checks: list[RateLimitCheck]) -> None:
    """Evaluates every rule of every check. Every rule is always recorded
    first — a request that trips one bucket still counts toward the
    others — and only then is a 429 raised if anything was exceeded, using
    the longest retry_after among violated rules.
    """
    violations: list[tuple[RateLimitCheck, RateLimitRule, int]] = []
    for check in checks:
        for rule in check.rules:
            bucket_key = f"{check.scope}:{rule.window_seconds}:{check.identity}"
            allowed, retry_after = _backend.hit(bucket_key, rule.window_seconds, rule.limit)
            if not allowed:
                violations.append((check, rule, retry_after))

    if not violations:
        return

    worst_check, worst_rule, retry_after = max(violations, key=lambda v: v[2])
    logger.warning(
        "rate_limit: blocked scope=%s identity_hash=%s limit=%s window=%ss retry_after=%ss",
        worst_check.scope,
        _safe_log_identity(worst_check.identity),
        worst_rule.limit,
        worst_rule.window_seconds,
        retry_after,
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": RATE_LIMIT_CODE, "message": RATE_LIMIT_MESSAGE},
        headers={"Retry-After": str(retry_after)},
    )


# --- identity helpers ------------------------------------------------------


def ip_identity(request: Request) -> str:
    return f"ip:{get_client_ip(request)}"


def user_identity(user_id: str) -> str:
    return f"user:{user_id}"


def user_ip_identity(request: Request, user_id: str) -> str:
    return f"user:{user_id}:ip:{get_client_ip(request)}"


def email_identity(email: str) -> str:
    """`email` must already be normalized (trimmed/lowercased — see
    schemas._normalize_email) so the same account can't dodge this bucket
    by varying case/whitespace. Hashed so the raw address never appears in
    a bucket key or, downstream, in a log line."""
    return f"email_hash:{hash_identifier(email)}"


# --- per-endpoint rule sets -------------------------------------------------

LOGIN_IP_RULES = (
    RateLimitRule(limit=5, window_seconds=60),
    RateLimitRule(limit=20, window_seconds=3600),
)
# Tighter than the IP-hour rule on purpose: this bucket exists specifically
# to catch distributed brute force against ONE account from MANY IPs, which
# is a stronger attack signal than generic per-IP volume, so it should trip
# sooner. A single hourly rule is enough here — spreading an attack across
# IPs is inherently a slower-paced strategy than a single-IP burst, so a
# per-minute account rule wouldn't add much beyond the IP rules above.
LOGIN_EMAIL_RULES = (RateLimitRule(limit=10, window_seconds=3600),)

REGISTER_RULES = (RateLimitRule(limit=3, window_seconds=3600),)
FORGOT_PASSWORD_RULES = (RateLimitRule(limit=3, window_seconds=3600),)
RESET_PASSWORD_RULES = (RateLimitRule(limit=10, window_seconds=3600),)
VERIFY_EMAIL_RULES = (RateLimitRule(limit=10, window_seconds=3600),)
RESEND_VERIFICATION_RULES = (RateLimitRule(limit=3, window_seconds=3600),)
SEND_INVOICE_EMAIL_RULES = (RateLimitRule(limit=10, window_seconds=3600),)

# Each import endpoint gets its own 10/hour budget (matching this file's
# existing one-scope-per-endpoint convention) rather than a single budget
# shared between preview and confirm.
IMPORT_PREVIEW_RULES = (RateLimitRule(limit=10, window_seconds=3600),)
IMPORT_CONFIRM_RULES = (RateLimitRule(limit=10, window_seconds=3600),)
