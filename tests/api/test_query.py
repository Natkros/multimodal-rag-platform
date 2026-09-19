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


def test_query_routes_table_question_to_table_chunk(client, monkeypatch, sample_docs_dir):
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())

    path = sample_docs_dir / "acme_vendor_security_policy.docx"
    with path.open("rb") as f:
        client.post("/documents/upload", files={"file": (path.name, f, "application/octet-stream")})

    resp = client.post("/query", json={"question": "Compare the vendor tiers in the table.", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["retrieval"]["matched_content_types"] == ["table"]
    assert all(s["content_type"] == "table" for s in body["sources"])


def test_query_routes_generic_question_without_content_type_restriction(client, monkeypatch):
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 5})
    assert resp.status_code == 200
    assert resp.json()["retrieval"]["matched_content_types"] == []


def test_query_with_hybrid_retrieval_mode(client, monkeypatch, test_settings):
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    test_settings.retrieval_mode = "hybrid"

    _upload(client, "facts.txt", b"Acme Corporation product code XZ-4471 was founded in 2010. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sources"]) >= 1
    assert body["retrieval"]["retrieved_chunks"] >= 1


def test_query_with_reranking_enabled_surfaces_stats(client, monkeypatch, test_settings):
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    test_settings.reranker_enabled = True

    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["retrieval"]["reranked"] is True
    assert body["retrieval"]["reranking_latency_ms"] is not None
    assert body["retrieval"]["reranking_latency_ms"] >= 0
    assert len(body["sources"]) <= 3


def test_query_without_reranking_reports_none_latency(client, monkeypatch):
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["retrieval"]["reranked"] is False
    assert body["retrieval"]["reranking_latency_ms"] is None


def test_query_reranking_corrects_misleading_top_result(client, monkeypatch, test_settings):
    """End-to-end: seed a corpus where a literal keyword overlap outranks the
    actually-relevant chunk, and confirm reranking (not just unit-level) fixes it
    through the real /query path."""
    import app.api.routes.query as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())

    _upload(
        client,
        "distractor.txt",
        b"The word Paris appears here but this document is entirely about growing "
        b"bananas and other tropical fruit cultivation techniques. Paris Paris Paris.",
    )
    _upload(client, "answer.txt", b"The capital city of France is Paris, a major European city.")

    test_settings.reranker_enabled = True
    resp = client.post("/query", json={"question": "What is the capital of France?", "top_k": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sources"]) == 1
    assert body["sources"][0]["document_name"] == "answer.txt"
