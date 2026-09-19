"""Phase 19: always-on request logging + Prometheus metrics — like security headers
(Phase 18), this has no legitimate-client-facing cost, so it isn't gated behind a
flag the way auth/rate limiting are. See docs/decisions/0019-phase19-observability.md.
"""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.services.observability.metrics import http_request_duration_seconds, http_requests_total

logger = logging.getLogger("app.request")


def _route_path(request: Request) -> str:
    """The matched route's path *template* (e.g. "/documents/{document_id}"), not
    the literal resolved URL — using the literal path as a Prometheus label would
    give every distinct document_id its own metric series (unbounded cardinality,
    a well-known Prometheus anti-pattern). Falls back to the literal path only when
    no route matched (404s have no route to template from)."""
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_s = time.perf_counter() - start

        path = _route_path(request)
        http_requests_total.labels(
            method=request.method, path=path, status_code=str(response.status_code)
        ).inc()
        http_request_duration_seconds.labels(method=request.method, path=path).observe(duration_s)

        logger.info(
            "request handled",
            extra={
                "http_method": request.method,
                "http_path": path,
                "status_code": response.status_code,
                "duration_ms": round(duration_s * 1000, 2),
            },
        )
        return response
