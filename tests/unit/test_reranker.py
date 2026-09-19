from __future__ import annotations

from app.services.reranking.reranker import CrossEncoderReranker
from app.services.retrieval.retriever import RetrievedChunk


def _chunk(chunk_id: str, text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="d1",
        document_name="doc.txt",
        text=text,
        page=1,
        section=None,
        score=score,
    )


def test_reranker_corrects_a_misleading_retrieval_order():
    """A candidate pool where the naive retrieval score ranks the wrong chunk first —
    the reranker (which actually reads query+chunk jointly) should fix that."""
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    candidates = [
        _chunk("wrong", "Bananas are a good source of potassium and fiber.", score=0.9),
        _chunk("right", "The Eiffel Tower is located in Paris, France.", score=0.5),
    ]

    reranked = reranker.rerank("Where is the Eiffel Tower located?", candidates, top_k=2)

    assert reranked[0].chunk_id == "right"


def test_reranker_scores_are_in_zero_one_range():
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    candidates = [_chunk("a", "Paris is the capital of France.", score=0.5)]
    reranked = reranker.rerank("What is the capital of France?", candidates, top_k=1)
    assert 0.0 <= reranked[0].score <= 1.0


def test_reranker_respects_top_k():
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    candidates = [_chunk(str(i), f"Some unrelated sentence number {i}.", score=0.1) for i in range(10)]
    reranked = reranker.rerank("Some query.", candidates, top_k=3)
    assert len(reranked) == 3


def test_reranker_empty_candidates_returns_empty():
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    assert reranker.rerank("anything", [], top_k=5) == []


def test_reranker_preserves_chunk_identity_fields():
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    candidates = [_chunk("a", "Paris is the capital of France.", score=0.5)]
    reranked = reranker.rerank("What is the capital of France?", candidates, top_k=1)
    assert reranked[0].chunk_id == "a"
    assert reranked[0].document_id == "d1"
    assert reranked[0].document_name == "doc.txt"
    assert reranked[0].page == 1
