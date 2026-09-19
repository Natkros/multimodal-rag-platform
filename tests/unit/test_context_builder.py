from __future__ import annotations

from app.services.generation.context_builder import build_context
from app.services.retrieval.retriever import RetrievedChunk


def _chunk(chunk_id, doc_id, text, score, content_type="text"):
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=doc_id,
        document_name=f"{doc_id}.txt",
        text=text,
        page=1,
        section=None,
        score=score,
        content_type=content_type,
    )


def test_default_behavior_unchanged_from_phase1_dedupe_and_budget():
    chunks = [
        _chunk("a", "d1", "First chunk text.", 0.9),
        _chunk("b", "d1", "First chunk text.", 0.5),  # duplicate text
        _chunk("c", "d1", "Second chunk text.", 0.7),
    ]
    result = build_context(chunks, max_tokens=3000)
    assert [c.chunk_id for c in result.chunks] == ["a", "c"]
    assert result.dropped_low_relevance == 0
    assert result.dropped_diversity_cap == 0
    assert result.truncated_chunks == 0


def test_source_distribution_always_computed():
    chunks = [
        _chunk("a", "d1", "Text A.", 0.9),
        _chunk("b", "d1", "Text B.", 0.8),
        _chunk("c", "d2", "Text C.", 0.7),
    ]
    result = build_context(chunks)
    assert result.source_distribution == {"d1.txt": 2, "d2.txt": 1}


def test_relevance_floor_drops_weak_candidates():
    chunks = [
        _chunk("a", "d1", "Strong match.", 0.9),
        _chunk("b", "d1", "Weak match.", 0.1),
    ]
    result = build_context(chunks, relevance_floor_ratio=0.5)
    assert [c.chunk_id for c in result.chunks] == ["a"]
    assert result.dropped_low_relevance == 1


def test_relevance_floor_disabled_by_default_keeps_everything():
    chunks = [
        _chunk("a", "d1", "Strong match.", 0.9),
        _chunk("b", "d1", "Weak match.", 0.05),
    ]
    result = build_context(chunks)
    assert len(result.chunks) == 2
    assert result.dropped_low_relevance == 0


def test_diversity_cap_limits_chunks_per_document():
    chunks = [
        _chunk("a", "d1", "D1 chunk one.", 0.9),
        _chunk("b", "d1", "D1 chunk two.", 0.8),
        _chunk("c", "d1", "D1 chunk three.", 0.7),
        _chunk("d", "d2", "D2 chunk one.", 0.6),
    ]
    result = build_context(chunks, max_chunks_per_document=2)
    doc_ids = [c.document_id for c in result.chunks]
    assert doc_ids.count("d1") == 2
    assert "d2" in doc_ids
    assert result.dropped_diversity_cap == 1


def test_diversity_cap_none_means_unlimited():
    chunks = [_chunk(str(i), "d1", f"Chunk {i}.", 0.9 - i * 0.01) for i in range(5)]
    result = build_context(chunks, max_chunks_per_document=None)
    assert len(result.chunks) == 5
    assert result.dropped_diversity_cap == 0


def test_compression_truncates_oversized_chunks():
    long_text = "word " * 500  # ~625 estimated tokens at 4 chars/token
    chunks = [_chunk("a", "d1", long_text, 0.9)]
    result = build_context(chunks, compression_enabled=True, max_chunk_tokens=50)
    assert result.truncated_chunks == 1
    assert result.chunks[0].text.endswith("[…truncated]")
    assert len(result.chunks[0].text) <= 50 * 4 + len(" […truncated]")


def test_compression_disabled_by_default_leaves_chunks_intact():
    long_text = "word " * 500
    chunks = [_chunk("a", "d1", long_text, 0.9)]
    result = build_context(chunks, max_tokens=10000)
    assert result.truncated_chunks == 0
    assert result.chunks[0].text == long_text


def test_compression_does_not_truncate_short_chunks():
    chunks = [_chunk("a", "d1", "Short text.", 0.9)]
    result = build_context(chunks, compression_enabled=True, max_chunk_tokens=50)
    assert result.truncated_chunks == 0
    assert result.chunks[0].text == "Short text."


def test_token_budget_still_respected_with_all_features_on():
    chunks = [_chunk(str(i), "d1", f"Chunk number {i} with some content here.", 0.9 - i * 0.01) for i in range(20)]
    result = build_context(
        chunks, max_tokens=50, relevance_floor_ratio=0.1, max_chunks_per_document=10, compression_enabled=True
    )
    assert result.total_tokens <= 50 or len(result.chunks) == 1  # always keeps at least one


def test_empty_chunks_returns_empty_context():
    result = build_context([])
    assert result.chunks == []
    assert result.source_distribution == {}
    assert result.total_tokens == 0
