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
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _HEADERS.items():
            response.headers[header] = value
        return response
