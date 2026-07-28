"""SSRF protection for outbound webhook deliveries.

A webhook endpoint URL is fully organization-controlled and this server
makes a real outbound POST to it -- the textbook SSRF surface (an
organization could point an endpoint at http://169.254.169.254/ or an
internal service and use this app as a proxy to reach it). Two layers:

1. `assert_public_url` -- a pre-flight check, run once when an endpoint
   URL is created/updated (app.services.webhook_endpoints) AND again
   immediately before every delivery attempt (defense in depth against a
   DNS record that was safe at creation time but repointed later).
   Resolves the hostname and rejects the URL if ANY resolved address is
   loopback/private/link-local/multicast/unspecified/reserved -- this
   single check already covers the cloud-metadata endpoint
   (169.254.169.254 is link-local).

2. `safe_connection_scope` -- closes the TOCTOU/DNS-rebinding gap that
   step 1 alone can't: nothing stops a hostname from resolving to a safe
   IP during the pre-flight check and a different, private IP by the time
   `requests` performs its own, separate resolution at actual socket-
   connect time. `requests` has no built-in hook for "validate the IP at
   the moment of connecting," so this context manager monkeypatches
   urllib3's `create_connection` (the one function every `requests` call
   ultimately routes through to open a TCP socket) for the duration of a
   single delivery attempt, re-validating the IP actually being connected
   to, not just the one seen during pre-flight. A lock serializes
   deliveries so two concurrent attempts never race on the same patched
   global function.

Residual risk, stated honestly: this closes the gap between pre-flight
and connect-time for THIS delivery attempt, but cannot prevent a
correctly-validated connection from later receiving an HTTP redirect to
an unsafe target -- which is why the delivery engine (see
app.services.webhook_deliveries) additionally disables redirect-following
entirely (`allow_redirects=False`) rather than trying to re-validate every
hop.
"""

import contextlib
import ipaddress
import socket
import threading
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"https", "http"}


class UnsafeWebhookUrlError(Exception):
    """The given URL is not eligible as a webhook delivery target -- never
    exposes *why* to an end user beyond a generic message (mirrors
    app.api_key_auth's anti-enumeration philosophy: no oracle for probing
    internal network layout), though the real reason is always logged
    server-side."""

    def __init__(self, url: str, reason: str):
        super().__init__(f"{reason}: {url}")
        self.reason = reason


def _is_unsafe_address(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def assert_public_url(url: str, *, allow_insecure_http: bool = False) -> None:
    """Raises UnsafeWebhookUrlError if `url` is not a safe webhook target.
    HTTPS is required unless allow_insecure_http is explicitly set (see
    app.services.webhook_endpoints -- reserved for local dev only, never
    enabled in production)."""
    parts = urlsplit(url)

    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeWebhookUrlError(url, "unsupported_scheme")
    if parts.scheme == "http" and not allow_insecure_http:
        raise UnsafeWebhookUrlError(url, "https_required")
    if parts.username or parts.password:
        raise UnsafeWebhookUrlError(url, "embedded_credentials_not_allowed")
    if not parts.hostname:
        raise UnsafeWebhookUrlError(url, "missing_host")

    try:
        resolved = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror:
        raise UnsafeWebhookUrlError(url, "dns_resolution_failed")

    if not resolved:
        raise UnsafeWebhookUrlError(url, "dns_resolution_failed")

    for family, _type, _proto, _canonname, sockaddr in resolved:
        candidate = sockaddr[0]
        try:
            if _is_unsafe_address(candidate):
                raise UnsafeWebhookUrlError(url, "resolves_to_non_public_address")
        except ValueError:
            raise UnsafeWebhookUrlError(url, "unparseable_address")


# Serializes access to the monkeypatched urllib3 connection function so two
# concurrent delivery attempts (this app runs route handlers in a thread
# pool -- see app.rate_limit's own docstring on this same fact) never
# install/restore each other's patch mid-flight.
_connection_patch_lock = threading.Lock()


@contextlib.contextmanager
def safe_connection_scope():
    """Patches urllib3.util.connection.create_connection for the duration
    of the `with` block so every TCP connection `requests` opens inside it
    is re-validated at actual connect time -- see this module's docstring
    for why pre-flight DNS validation alone isn't sufficient."""
    import urllib3.util.connection as urllib3_connection

    original_create_connection = urllib3_connection.create_connection

    def patched_create_connection(address, *args, **kwargs):
        host, _port = address
        try:
            ipaddress.ip_address(host)
            candidate_is_literal_ip = True
        except ValueError:
            candidate_is_literal_ip = False

        if candidate_is_literal_ip:
            if _is_unsafe_address(host):
                raise UnsafeWebhookUrlError(host, "resolves_to_non_public_address")
        else:
            resolved = socket.getaddrinfo(host, None)
            if not resolved or any(_is_unsafe_address(info[4][0]) for info in resolved):
                raise UnsafeWebhookUrlError(host, "resolves_to_non_public_address")

        return original_create_connection(address, *args, **kwargs)

    with _connection_patch_lock:
        urllib3_connection.create_connection = patched_create_connection
        try:
            yield
        finally:
            urllib3_connection.create_connection = original_create_connection
