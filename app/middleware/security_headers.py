"""Phase 18: always-on response security headers — unlike auth/rate limiting, these
have no legitimate-client-facing downside (no request is ever rejected because of
them), so there's no reason to gate them behind a flag. See
docs/decisions/0018-phase18-security-hardening.md for what's included and why no
Content-Security-Policy header is set (this is a JSON API, not an HTML-serving app;
a CSP is the wrong tool here and would only add noise).
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Production hardening: tells a browser to only ever talk to this host over
    # HTTPS for the next year, including subdomains, once it has seen this header
    # once over a genuine HTTPS connection. Safe to send unconditionally — per the
    # HSTS spec, a browser ignores this header entirely when received over plain
    # HTTP, so it has no effect in local dev (http://localhost) and only matters
    # once this service actually sits behind TLS (e.g. Render's default HTTPS
    # termination, or a production reverse proxy).
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _HEADERS.items():
            response.headers[header] = value
        return response
