from __future__ import annotations

from app.services.chunking.semantic_chunker import _split_sentences, _tail_sentences, semantic_chunk
from app.services.extraction.loaders import ExtractedPage


class FakeEmbedder:
    """Deterministic fake: sentences with the given `similar_group` id get identical
    (already-normalized) vectors, so cosine similarity is 1.0 within a group and
    orthogonal (0.0) across groups — makes topic-break behavior exactly predictable
    without depending on a real model's actual similarity scores."""

    def __init__(self, group_for_sentence: dict[str, int]):
        self._groups = group_for_sentence

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            group = self._groups[text]
            vec = [0.0, 0.0, 0.0]
            vec[group % 3] = 1.0
            vectors.append(vec)
        return vectors


def test_split_sentences_basic():
    text = "First sentence. Second sentence! Third one?"
    assert _split_sentences(text) == ["First sentence.", "Second sentence!", "Third one?"]


def test_split_sentences_empty_text():
    assert _split_sentences("   ") == []


def test_tail_sentences_respects_char_budget():
    sentences = ["A short one.", "Another short one.", "Yet another."]
    tail = _tail_sentences(sentences, max_overlap_chars=15)
    assert tail == ["Yet another."]


def test_tail_sentences_zero_budget_returns_empty():
    assert _tail_sentences(["Something."], max_overlap_chars=0) == []


def test_semantic_chunk_breaks_on_topic_change():
    s1, s2, s3, s4 = "Topic A sentence one.", "Topic A sentence two.", "Topic B begins here.", "Topic B continues."
    embedder = FakeEmbedder({s1: 0, s2: 0, s3: 1, s4: 1})
    pages = [ExtractedPage(page_number=1, text=f"{s1} {s2} {s3} {s4}")]

    chunks = semantic_chunk(pages, chunk_size_tokens=1000, overlap_tokens=0, embedder=embedder, similarity_threshold=0.5)

    assert len(chunks) == 2
    assert s1 in chunks[0].text and s2 in chunks[0].text
    assert s3 in chunks[1].text and s4 in chunks[1].text


def test_semantic_chunk_keeps_similar_sentences_together():
    s1, s2, s3 = "A.", "B.", "C."
    embedder = FakeEmbedder({s1: 0, s2: 0, s3: 0})
    pages = [ExtractedPage(page_number=1, text=f"{s1} {s2} {s3}")]

    chunks = semantic_chunk(pages, chunk_size_tokens=1000, overlap_tokens=0, embedder=embedder, similarity_threshold=0.5)

    assert len(chunks) == 1
    assert chunks[0].text == "A. B. C."


def test_semantic_chunk_respects_token_budget_even_when_similar():
    sentences = [f"Sentence number {i} about the same topic." for i in range(20)]
    embedder = FakeEmbedder({s: 0 for s in sentences})
    pages = [ExtractedPage(page_number=1, text=" ".join(sentences))]

    chunks = semantic_chunk(pages, chunk_size_tokens=15, overlap_tokens=0, embedder=embedder, similarity_threshold=0.5)

    assert len(chunks) > 1
    assert all(len(c.text) <= 15 * 4 + 60 for c in chunks)  # small slack for the sentence that triggers the break


def test_semantic_chunk_requires_embedder():
    import pytest

    pages = [ExtractedPage(page_number=1, text="Some text.")]
    with pytest.raises(ValueError):
        semantic_chunk(pages, chunk_size_tokens=100, overlap_tokens=0, embedder=None)


def test_semantic_chunk_single_sentence_page():
    embedder = FakeEmbedder({"Only one sentence here.": 0})
    pages = [ExtractedPage(page_number=1, text="Only one sentence here.")]
    chunks = semantic_chunk(pages, chunk_size_tokens=100, overlap_tokens=0, embedder=embedder)
    assert len(chunks) == 1
    assert chunks[0].text == "Only one sentence here."


def test_semantic_chunk_empty_page_produces_no_chunks():
    embedder = FakeEmbedder({})
    pages = [ExtractedPage(page_number=1, text="   ")]
    chunks = semantic_chunk(pages, chunk_size_tokens=100, overlap_tokens=0, embedder=embedder)
    assert chunks == []
