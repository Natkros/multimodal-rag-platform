from __future__ import annotations


class FakeLLMClient:
    def complete(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        return "Acme was founded in 2010 [1]."


def _upload(client, filename: str, content: bytes, content_type: str = "text/plain"):
    return client.post("/documents/upload", files={"file": (filename, content, content_type)})


def test_query_without_llm_configured_returns_503(client):
    _upload(client, "facts.txt", b"Acme was founded in 2010 in Austin, Texas. " * 5)
    resp = client.post("/query", json={"question": "When was Acme founded?"})
    assert resp.status_code == 503


def test_query_with_no_matching_documents_abstains(client, monkeypatch):
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    resp = client.post("/query", json={"question": "What is the capital of France?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["confidence"] == "abstained"
    assert "could not find sufficient evidence" in body["answer"]
    assert body["sources"] == []


def test_query_grounded_answer_with_sources(client, monkeypatch):
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())

    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)

    resp = client.post("/query", json={"question": "When and where was Acme founded?", "top_k": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Acme was founded in 2010 [1]."
    assert body["confidence"] in ("high", "low")
    assert len(body["sources"]) >= 1
    assert body["retrieval"]["retrieved_chunks"] >= 1
    assert body["retrieval"]["total_latency_ms"] >= 0


def test_query_validates_empty_question(client):
    resp = client.post("/query", json={"question": ""})
    assert resp.status_code == 422


def test_query_document_scoped_filtering(client, monkeypatch):
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())

    up1 = _upload(client, "doc1.txt", b"Acme Corporation was founded in 2010. " * 3)
    doc1_id = up1.json()["document_id"]
    _upload(client, "doc2.txt", b"Beta Industries was founded in 1999. " * 3)

    resp = client.post(
        "/query",
        json={"question": "When was the company founded?", "document_ids": [doc1_id], "top_k": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    for source in body["sources"]:
        assert source["document_id"] == doc1_id
