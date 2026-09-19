from __future__ import annotations

from app.services.observability.metrics import http_requests_total


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def test_metrics_endpoint_returns_prometheus_text_format(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "http_requests_total" in resp.text


def test_metrics_endpoint_does_not_require_api_key(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "api_key", "secret-key")
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_a_request_increments_the_request_counter(client):
    before = _counter_value(http_requests_total, method="GET", path="/health", status_code="200")
    client.get("/health")
    after = _counter_value(http_requests_total, method="GET", path="/health", status_code="200")
    assert after == before + 1


def test_request_counter_uses_route_template_not_literal_path(client):
    """Two different document_ids hitting GET /documents/{document_id} should both
    count against the same templated label, not create two separate series -
    otherwise every distinct id would blow up cardinality."""
    before = _counter_value(http_requests_total, method="GET", path="/documents/{document_id}", status_code="404")
    client.get("/documents/nonexistent-id-1")
    client.get("/documents/nonexistent-id-2")
    after = _counter_value(http_requests_total, method="GET", path="/documents/{document_id}", status_code="404")
    assert after == before + 2
