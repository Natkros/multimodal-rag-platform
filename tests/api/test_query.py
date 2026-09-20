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
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    resp = client.post("/query", json={"question": "What is the capital of France?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["confidence"] == "abstained"
    assert "could not find sufficient evidence" in body["answer"]
    assert body["sources"] == []


def test_query_grounded_answer_with_sources(client, monkeypatch):
    import app.services.query_service as query_module

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
    import app.services.query_service as query_module

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
    import app.services.query_service as query_module

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
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 5})
    assert resp.status_code == 200
    assert resp.json()["retrieval"]["matched_content_types"] == []


def test_query_with_hybrid_retrieval_mode(client, monkeypatch, test_settings):
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    test_settings.retrieval_mode = "hybrid"

    _upload(client, "facts.txt", b"Acme Corporation product code XZ-4471 was founded in 2010. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sources"]) >= 1
    assert body["retrieval"]["retrieved_chunks"] >= 1


def test_query_with_reranking_enabled_surfaces_stats(client, monkeypatch, test_settings):
    import app.services.query_service as query_module

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


def test_query_with_mmr_enabled_returns_diverse_results(client, monkeypatch, test_settings):
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    test_settings.mmr_enabled = True

    _upload(client, "facts1.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)
    _upload(client, "facts2.txt", b"Acme Corporation was founded in 2010 in Austin, Texas, too. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 3})
    assert resp.status_code == 200
    assert len(resp.json()["sources"]) <= 3


def test_query_with_mmr_and_reranking_both_enabled(client, monkeypatch, test_settings):
    """MMR needs a real pool bigger than top_k to diversify from - confirms
    reranking a wider pool (not trimmed to top_k) when MMR will run afterward
    doesn't break the combined pipeline."""
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    test_settings.mmr_enabled = True
    test_settings.reranker_enabled = True

    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 2})
    assert resp.status_code == 200
    assert len(resp.json()["sources"]) <= 2


def test_query_without_reranking_reports_none_latency(client, monkeypatch):
    import app.services.query_service as query_module

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
    import app.services.query_service as query_module

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


class SmartFakeLLMClient:
    """Dispatches on which system prompt is used, so one instance can stand in for
    generation *and* query-intelligence (rewrite/decompose) calls in the same request."""

    def __init__(self, generation_answer="The answer is here [1].", rewrite=None, decompose=None):
        self.generation_answer = generation_answer
        self.rewrite = rewrite
        self.decompose = decompose
        self.calls = []

    def complete(self, system, user, max_tokens, temperature):
        self.calls.append((system, user))
        system_lower = system.lower()
        if "rewrite" in system_lower:
            return self.rewrite or ""
        if "break a multi-part" in system_lower:
            return self.decompose or ""
        if "alternative phrasings" in system_lower:
            return ""
        return self.generation_answer


def _patch_llm_everywhere(monkeypatch, fake_client):
    import app.services.query_intelligence.pipeline as pipeline_module
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: fake_client)
    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda settings: fake_client)


def test_query_intelligence_absent_by_default(client, monkeypatch):
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?"})
    assert resp.status_code == 200
    assert resp.json()["query_intelligence"] is None


def test_query_follow_up_resolved_across_two_turns(client, monkeypatch, test_settings):
    test_settings.query_intelligence_enabled = True
    fake_client = SmartFakeLLMClient(
        generation_answer="Q2 2025 revenue was $42.3 million [1].",
        rewrite="What was Acme's Q2 2025 revenue?",
    )
    _patch_llm_everywhere(monkeypatch, fake_client)

    _upload(
        client,
        "revenue.txt",
        b"Acme's Q1 2025 revenue was $38 million. Acme's Q2 2025 revenue was $42.3 million. " * 3,
    )

    first = client.post(
        "/query", json={"question": "What was Acme's Q1 2025 revenue?", "conversation_id": "conv-1"}
    )
    assert first.status_code == 200

    second = client.post("/query", json={"question": "What about Q2?", "conversation_id": "conv-1"})
    assert second.status_code == 200
    body = second.json()
    assert body["query_intelligence"]["is_follow_up"] is True
    assert body["query_intelligence"]["rewritten"] is True
    assert body["query_intelligence"]["effective_question"] == "What was Acme's Q2 2025 revenue?"
    assert body["query_intelligence"]["retrieval_trace"][0]["query"] == "What was Acme's Q2 2025 revenue?"


def test_query_decomposition_tracks_each_retrieval_operation(client, monkeypatch, test_settings):
    test_settings.query_intelligence_enabled = True
    fake_client = SmartFakeLLMClient(
        decompose=(
            "What was Acme's 2023 revenue?\n"
            "What was Acme's 2024 revenue?\n"
            "What drove Acme's revenue growth?"
        )
    )
    _patch_llm_everywhere(monkeypatch, fake_client)

    _upload(
        client,
        "revenue.txt",
        b"Acme's 2023 revenue was $100 million. Acme's 2024 revenue was $130 million, "
        b"driven by Enterprise tier growth. " * 3,
    )

    resp = client.post(
        "/query",
        json={"question": "Compare revenue growth between 2023 and 2024 and explain the primary drivers."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["query_intelligence"]["sub_questions"]) == 3
    assert len(body["query_intelligence"]["retrieval_trace"]) == 3
    queries = [entry["query"] for entry in body["query_intelligence"]["retrieval_trace"]]
    assert "What was Acme's 2023 revenue?" in queries
    assert "What was Acme's 2024 revenue?" in queries


def test_query_auto_scopes_to_mentioned_document(client, monkeypatch, test_settings, sample_docs_dir):
    test_settings.query_intelligence_enabled = True
    fake_client = SmartFakeLLMClient()
    _patch_llm_everywhere(monkeypatch, fake_client)

    path = sample_docs_dir / "acme_vendor_security_policy.docx"
    with path.open("rb") as f:
        client.post("/documents/upload", files={"file": (path.name, f, "application/octet-stream")})
    _upload(client, "handbook.txt", b"Acme's remote work policy allows three days per week. " * 3)

    resp = client.post(
        "/query", json={"question": "In the vendor security policy, what is the Tier 1 requirement?"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query_intelligence"]["matched_document_id"] is not None
    for source in body["sources"]:
        assert source["document_id"] == body["query_intelligence"]["matched_document_id"]


def test_query_reports_source_distribution(client, monkeypatch):
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 5)

    resp = client.post("/query", json={"question": "When was Acme founded?", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["retrieval"]["source_distribution"]
    assert sum(body["retrieval"]["source_distribution"].values()) == len(body["sources"])
    assert body["retrieval"]["dropped_low_relevance"] == 0
    assert body["retrieval"]["dropped_diversity_cap"] == 0


def test_query_diversity_cap_limits_sources_per_document(client, monkeypatch, test_settings):
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    test_settings.context_max_chunks_per_document = 1

    _upload(
        client,
        "facts.txt",
        b"Acme was founded in 2010 in Austin. " * 3
        + b"Acme's headquarters moved to Dallas in 2015. " * 3
        + b"Acme went public in 2020 on the Nasdaq exchange. " * 3,
    )

    resp = client.post("/query", json={"question": "Tell me about Acme's history.", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    for count in body["retrieval"]["source_distribution"].values():
        assert count <= 1


def test_query_citation_validation_flags_fabricated_number(client, monkeypatch):
    import app.services.query_service as query_module

    class FabricatingLLMClient:
        def complete(self, system, user, max_tokens, temperature):
            return "Acme's Q2 2025 revenue was $999 million [1]."

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FabricatingLLMClient())
    _upload(client, "revenue.txt", b"Acme's Q2 2025 revenue was $42.3 million, up 18% year over year. " * 3)

    resp = client.post("/query", json={"question": "What was Acme's Q2 2025 revenue?", "top_k": 3})
    assert resp.status_code == 200
    body = resp.json()
    cv = body["citation_validation"]
    assert cv is not None
    assert cv["total_claims"] == 1
    assert cv["supported_claims"] == 0
    assert cv["citation_correctness"] == 0.0
    assert "$999" in cv["unsupported_claims"][0]["missing_numbers"]


def test_query_citation_validation_passes_for_accurate_answer(client, monkeypatch):
    import app.services.query_service as query_module

    class AccurateLLMClient:
        def complete(self, system, user, max_tokens, temperature):
            return "Acme's Q2 2025 revenue was $42.3 million [1]."

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: AccurateLLMClient())
    _upload(client, "revenue.txt", b"Acme's Q2 2025 revenue was $42.3 million, up 18% year over year. " * 3)

    resp = client.post("/query", json={"question": "What was Acme's Q2 2025 revenue?", "top_k": 3})
    assert resp.status_code == 200
    cv = resp.json()["citation_validation"]
    assert cv["citation_correctness"] == 1.0


def test_query_citation_validation_absent_when_disabled(client, monkeypatch, test_settings):
    import app.services.query_service as query_module

    monkeypatch.setattr(query_module, "get_llm_client", lambda settings: FakeLLMClient())
    test_settings.citation_validation_enabled = False
    _upload(client, "facts.txt", b"Acme Corporation was founded in 2010 in Austin, Texas. " * 3)

    resp = client.post("/query", json={"question": "When was Acme founded?"})
    assert resp.status_code == 200
    assert resp.json()["citation_validation"] is None
