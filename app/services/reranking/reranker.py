"""Cross-encoder reranking (Phase 7): re-scores a candidate pool with a model that
looks at the (query, chunk) pair jointly, which is more accurate but far more
expensive per-item than a retriever comparing a query vector against millions of
precomputed chunk vectors independently. That's why it runs on a small candidate pool
(`RERANK_CANDIDATE_POOL`, e.g. top 30) rather than the whole corpus — see
app/services/retrieval/retriever.py for the retrieval stage that produces the pool.

Opt-in (`RERANKER_ENABLED=false` by default) so Phase 1-6's baseline stays
reproducible without it; see docs/decisions/0007-phase7-reranking.md for the measured
before/after comparison this exists to make possible, per the project rule: "do not
assume reranking improves the system; prove it experimentally."
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings
from app.services.retrieval.retriever import RetrievedChunk


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, candidates: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        if not candidates:
            return []

        import torch

        pairs = [(query, c.text) for c in candidates]
        # Sigmoid activation keeps scores in (0, 1) — the same range dense cosine
        # similarity and Phase 6's rescaled RRF fusion already use, so
        # GROUNDING_CONFIDENCE_THRESHOLD and the "high"/"low" confidence label in
        # app/services/generation/generator.py stay meaningful after reranking
        # without a separate threshold just for this stage. Raw cross-encoder logits
        # (no activation) are unbounded and would silently break that comparison.
        scores = self._model.predict(pairs, activation_fn=torch.nn.Sigmoid())

        reranked = [
            RetrievedChunk(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_name=c.document_name,
                text=c.text,
                page=c.page,
                section=c.section,
                score=float(score),
                content_type=c.content_type,
            )
            for c, score in zip(candidates, scores, strict=True)
        ]
        reranked.sort(key=lambda c: c.score, reverse=True)
        return reranked[:top_k]


@lru_cache(maxsize=2)
def _cached_reranker(model_name: str) -> CrossEncoderReranker:
    return CrossEncoderReranker(model_name)


def get_reranker(settings: Settings) -> CrossEncoderReranker:
    return _cached_reranker(settings.reranker_model)
