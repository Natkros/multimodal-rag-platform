"""Phase 18: opt-in Redis-backed rate limiting (`RATE_LIMIT_ENABLED=true`, off by
default). A fixed-window counter (`INCR` + `EXPIRE` on a per-client, per-minute key)
rather than a token bucket or sliding-log — simpler, correct enough for this
project's needs, and the standard first reach-for for a fixed requests-per-minute
budget. See docs/decisions/0018-phase18-security-hardening.md.
"""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import Settings

logger = logging.getLogger(__name__)

_EXEMPT_PATHS = {"/health", "/ready", "/docs", "/openapi.json", "/redoc"}


def _client_identifier(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key}"
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        if not self.settings.rate_limit_enabled or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        window = int(time.time() // 60)
        key = f"ratelimit:{_client_identifier(request)}:{window}"

        try:
            from app.services.caching.cache import get_redis_client

            client = get_redis_client(self.settings)
            count = client.incr(key)
            if count == 1:
                client.expire(key, 60)
        except Exception:
            # Fail open: a Redis outage should degrade to "no rate limiting", not
            # "API is down" — this dependency is a hardening measure, not a
            # correctness requirement the way the database is.
            logger.warning("Rate limiter could not reach Redis; allowing request unthrottled.")
            return await call_next(request)

        if count > self.settings.rate_limit_requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in a moment."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
