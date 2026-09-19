"""Phase 19: Prometheus metrics, exposed at GET /metrics (app/api/routes/health.py).
A module-level `prometheus_client` registry (its default global one) rather than a
per-Settings object — metrics are inherently process-wide state, unlike
Settings/embedders/vector stores, which this project deliberately makes swappable
per test. See docs/decisions/0019-phase19-observability.md.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

retrieval_cache_total = Counter(
    "retrieval_cache_total",
    "Retrieval cache lookups (Phase 17)",
    ["result"],  # "hit" | "miss"
)

rate_limit_rejections_total = Counter(
    "rate_limit_rejections_total",
    "Requests rejected by the rate limiter (Phase 18)",
)
