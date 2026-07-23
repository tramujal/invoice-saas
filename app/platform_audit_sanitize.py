"""Sanitization helpers for rendering PlatformAuditLog rows back to a
platform admin.

`details` is a free-form JSON-as-TEXT column written by whichever call
site created the row (see app.services.platform_audit) -- it must be
treated as untrusted historical data when read back, not a trusted
schema, since nothing stops some future caller from putting more into it
than today's {"old_role": ..., "new_role": ...} shape. mask_client_ip
protects the other PII-shaped field on the same read path: a list view
of every admin action doesn't need street-level location precision to
be useful.
"""

import ipaddress
import json

_REDACTED = "[redacted]"
_SENSITIVE_KEY_MARKERS = ("token", "password", "secret", "api_key", "authorization", "cookie", "hash")
_MAX_SERIALIZED_DETAILS_BYTES = 4096


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _redact(value):
    if isinstance(value, dict):
        return {k: (_REDACTED if _is_sensitive_key(k) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def sanitize_audit_details(raw: str | None) -> dict | None:
    """Parses `details` and recursively redacts any key that looks like
    it could hold a secret, regardless of which call site originally
    wrote it -- defense in depth, not a guarantee today's writers ever
    produce such a key. Never raises: returns None for anything that
    isn't parseable JSON, isn't an object at the top level, or
    serializes back out over the size limit, since a malformed or
    oversized historical row must never break the audit-log listing."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None

    redacted = _redact(parsed)
    if len(json.dumps(redacted)) > _MAX_SERIALIZED_DETAILS_BYTES:
        return None
    return redacted


def mask_client_ip(ip: str | None) -> str | None:
    """Partial masking -- an IPv4 address to its /24 network, IPv6 to
    its /48 -- enough to correlate repeated actions from roughly the
    same network without exposing the admin's precise address. Returns
    None for anything unparseable, including the "unknown" sentinel
    app.rate_limit.get_client_ip returns when no IP could be
    determined."""
    if not ip:
        return None
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = 24 if parsed.version == 4 else 48
    network = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
    return str(network.network_address)
