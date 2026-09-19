from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.core.config import get_settings
from app.services.retrieval.retriever import CachingRetriever, RetrievalResult, RetrievedChunk


def _settings(**overrides):
    return get_settings().model_copy(update=overrides)


def _sample_result() -> RetrievalResult:
    return RetrievalResult(
        chunks=[
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                document_name="doc.txt",
                text="Acme was founded in 2010.",
                page=None,
                section=None,
                score=0.9,
                content_type="text",
            )
        ],
        matched_content_types=[],
    )


def test_cache_miss_calls_inner_and_stores_result():
    inner = MagicMock()
    inner.retrieve_with_classification.return_value = _sample_result()
    settings = _settings(cache_enabled=True)
    retriever = CachingRetriever(inner, settings)

    with patch("app.services.caching.cache.cache_get", return_value=None) as mock_get, patch(
        "app.services.caching.cache.cache_set"
    ) as mock_set:
        result = retriever.retrieve_with_classification("When was Acme founded?", top_k=5)

    inner.retrieve_with_classification.assert_called_once_with("When was Acme founded?", 5, None)
    assert result.chunks[0].chunk_id == "c1"
    mock_get.assert_called_once()
    mock_set.assert_called_once()


def test_cache_hit_does_not_call_inner():
    inner = MagicMock()
    settings = _settings(cache_enabled=True)
    retriever = CachingRetriever(inner, settings)

    cached_payload = json.dumps(
        {
            "chunks": [
                {
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "document_name": "doc.txt",
                    "text": "Acme was founded in 2010.",
                    "page": None,
                    "section": None,
                    "score": 0.9,
                    "content_type": "text",
                }
            ],
            "matched_content_types": [],
        }
    )

    with patch("app.services.caching.cache.cache_get", return_value=cached_payload):
        result = retriever.retrieve_with_classification("When was Acme founded?", top_k=5)

    inner.retrieve_with_classification.assert_not_called()
    assert result.chunks[0].chunk_id == "c1"
    assert result.chunks[0].text == "Acme was founded in 2010."


def test_cache_key_differs_by_query_top_k_and_document_ids():
    settings = _settings(cache_enabled=True)
    retriever = CachingRetriever(MagicMock(), settings)

    key1 = retriever._cache_key("question one", 5, None)
    key2 = retriever._cache_key("question two", 5, None)
    key3 = retriever._cache_key("question one", 10, None)
    key4 = retriever._cache_key("question one", 5, ["doc-1"])
    key5 = retriever._cache_key("question one", 5, ["doc-2", "doc-1"])
    key6 = retriever._cache_key("question one", 5, ["doc-1", "doc-2"])

    assert len({key1, key2, key3, key4}) == 4
    assert key5 == key6  # document_ids order shouldn't matter — both get sorted


def test_get_retriever_wraps_in_caching_retriever_when_enabled(test_settings):
    from app.services.embeddings.factory import get_embedder
    from app.services.retrieval.factory import get_retriever, get_vector_store
    from app.services.retrieval.retriever import CachingRetriever, DenseRetriever

    test_settings.cache_enabled = False
    embedder = get_embedder(test_settings)
    vector_store = get_vector_store(test_settings, embedder.dimension)
    plain = get_retriever(test_settings, embedder, vector_store)
    assert isinstance(plain, DenseRetriever)

    test_settings.cache_enabled = True
    wrapped = get_retriever(test_settings, embedder, vector_store)
    assert isinstance(wrapped, CachingRetriever)
    assert isinstance(wrapped.inner, DenseRetriever)
