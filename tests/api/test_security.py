from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_security_headers_present_on_every_response(client):
    resp = client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_unhandled_exception_returns_generic_500_with_error_id_not_a_stack_trace(test_settings, monkeypatch):
    """Production hardening: an unhandled exception must never leak internals
    (file paths, exception type, stack trace) to the client, but must still be
    traceable server-side via a returned error_id.

    Uses its own TestClient with raise_server_exceptions=False: Starlette's
    ServerErrorMiddleware sends the registered handler's response to the wire
    exactly as a real HTTP client would receive it, but also always re-raises the
    exception into the ASGI call stack so an in-process test run surfaces a real
    bug loudly by default - the same reason every other test in this suite
    deliberately keeps that default. This one test needs to instead observe the
    response the way an external caller genuinely would."""
    from fastapi.testclient import TestClient

    import app.api.routes.query as query_route_module
    from app.main import create_app
    from app.models.db import init_db

    def boom(request, db, settings):
        raise RuntimeError("something broke internally: /secret/path")

    monkeypatch.setattr(query_route_module, "run_query_pipeline", boom)

    init_db()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/query", json={"question": "Anything?"})

    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal server error."
    assert "error_id" in body
    assert "/secret/path" not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text


def test_no_api_key_required_by_default(client):
    resp = client.get("/documents")
    assert resp.status_code == 200


def test_health_and_ready_never_require_api_key(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "api_key", "secret-key")
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_missing_api_key_rejected_when_configured(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "api_key", "secret-key")
    resp = client.get("/documents")
    assert resp.status_code == 401


def test_wrong_api_key_rejected(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "api_key", "secret-key")
    resp = client.get("/documents", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_correct_api_key_accepted(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "api_key", "secret-key")
    resp = client.get("/documents", headers={"X-API-Key": "secret-key"})
    assert resp.status_code == 200


def test_rate_limiting_disabled_by_default_allows_many_requests(client):
    for _ in range(10):
        resp = client.get("/documents")
        assert resp.status_code == 200


def test_rate_limit_exceeded_returns_429(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "rate_limit_enabled", True)
    monkeypatch.setattr(test_settings, "rate_limit_requests_per_minute", 3)

    mock_redis = MagicMock()
    counts = iter([1, 2, 3, 4, 5])
    mock_redis.incr.side_effect = lambda key: next(counts)

    with patch("app.services.caching.cache.get_redis_client", return_value=mock_redis):
        statuses = [client.get("/documents").status_code for _ in range(4)]

    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


def test_rate_limiter_fails_open_when_redis_unreachable(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "rate_limit_enabled", True)

    with patch("app.services.caching.cache.get_redis_client", side_effect=ConnectionError("no redis")):
        resp = client.get("/documents")

    assert resp.status_code == 200


def test_rate_limit_exempts_health_endpoint(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "rate_limit_enabled", True)
    monkeypatch.setattr(test_settings, "rate_limit_requests_per_minute", 1)

    mock_redis = MagicMock()
    mock_redis.incr.return_value = 999  # would exceed any limit if health weren't exempt

    with patch("app.services.caching.cache.get_redis_client", return_value=mock_redis):
        for _ in range(5):
            assert client.get("/health").status_code == 200
