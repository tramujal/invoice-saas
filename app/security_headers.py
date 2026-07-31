"""Standard security response headers -- defense-in-depth for the
browser-facing surface of this API. The JSON endpoints themselves aren't
typically vulnerable to clickjacking/MIME-sniffing the way an HTML page
is, but the interactive docs at /docs and /redoc ARE full HTML pages, and
every error response is still something a browser could attempt to sniff
or frame -- these headers cost nothing for non-browser clients (curl, the
frontend's own fetch calls, every Organization-API-Key integration) since
only a browser ever interprets any of them.

Deliberately no Content-Security-Policy here: /docs (Swagger UI) loads
its JS/CSS from a CDN by default, and a CSP tight enough to matter would
need to be built specifically around exactly which values that page and
ReDoc use -- getting it wrong silently breaks the docs UI rather than
failing loudly. See docs/deployment.md's own security-headers section
for the recommended reverse-proxy/CDN-layer CSP instead, scoped to the
Next.js frontend, which serves real HTML pages and has no such CDN
dependency to account for.
"""

from starlette.responses import Response

_PERMISSIONS_POLICY = "geolocation=(), microphone=(), camera=()"


def apply_security_headers(response: Response) -> None:
    """Mutates `response.headers` in place -- called from main.py's own
    middleware after call_next() returns, so it applies uniformly to
    every route (including error responses, which FastAPI's exception
    handlers still return as ordinary Response objects through the same
    middleware chain)."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = _PERMISSIONS_POLICY
    # Only meaningful to a browser that received this response over
    # HTTPS -- per RFC 6797 §7.2, browsers ignore Strict-Transport-
    # Security entirely when the response arrived over plain HTTP, so
    # sending it unconditionally (including during local HTTP dev) is
    # safe. Deliberately not gated on request.url.scheme: behind
    # Render's reverse proxy, TLS is terminated before this app ever
    # sees the request, so that would always read "http" here anyway
    # even in production -- see app.rate_limit's own module docstring
    # for the same "this app never sees the original scheme/IP directly"
    # constraint applied to client-IP resolution.
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
