from __future__ import annotations

import json
import logging

from app.core.config import get_settings
from app.services.observability.logging_config import JsonFormatter, configure_logging


def _settings(**overrides):
    return get_settings().model_copy(update=overrides)


def test_json_formatter_produces_valid_json_with_core_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1, msg="hello world", args=(), exc_info=None
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["level"] == "INFO"
    assert data["logger"] == "app.test"
    assert data["message"] == "hello world"
    assert "timestamp" in data


def test_json_formatter_includes_extra_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1, msg="request handled", args=(), exc_info=None
    )
    record.status_code = 200
    record.duration_ms = 12.5
    output = formatter.format(record)
    data = json.loads(output)
    assert data["status_code"] == 200
    assert data["duration_ms"] == 12.5


def test_configure_logging_uses_json_formatter_when_enabled():
    settings = _settings(log_json=True)
    configure_logging(settings)
    root = logging.getLogger()
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_uses_plain_formatter_by_default():
    settings = _settings(log_json=False)
    configure_logging(settings)
    root = logging.getLogger()
    assert not isinstance(root.handlers[0].formatter, JsonFormatter)
