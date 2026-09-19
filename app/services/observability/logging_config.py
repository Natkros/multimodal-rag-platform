"""Phase 19: structured logging. `LOG_JSON` (scaffolded since Phase 1, unused
until now) switches between plain-text logs (default — readable in a local
terminal) and one-JSON-object-per-line logs (production/log-aggregator friendly —
Docker/Kubernetes deployments typically want this so a log shipper doesn't have to
parse free text). See docs/decisions/0019-phase19-observability.md.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from app.core.config import Settings

_RESERVED_LOG_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys())


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Anything passed via logger.info("msg", extra={...}) — request_id,
        # duration_ms, status_code, etc. — rides along as top-level JSON fields
        # rather than being swallowed, which is the whole point of structured
        # logging: a log shipper can filter/aggregate on these without regex.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()

    handler = logging.StreamHandler()
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
