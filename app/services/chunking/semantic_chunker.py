"""Semantic (embedding-similarity) chunking — the third strategy required by Phase 3.

Unlike `fixed_size_chunk` (blind token windows) and `recursive_chunk` (splits on
markdown structure), this strategy splits on *topic drift*: it embeds consecutive
sentences and starts a new chunk wherever the cosine similarity between adjacent
sentences drops below a threshold, so a chunk boundary falls where the subject
actually changes rather than where a heading or a token-count happens to land. It
still respects the token budget as a hard cap.

Costs an embedding call per sentence (`embedder.embed_documents`), which is
meaningfully slower than the other two strategies — see the comparison report in
evaluation/reports/ for measured latency, not a guess.
"""
from __future__ import annotations

import re

import numpy as np

from app.services.chunking.chunker import Chunk, estimate_tokens

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def _split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    pieces = _SENTENCE_RE.split(text)
    return [p.strip() for p in pieces if p.strip()]


def semantic_chunk(
    pages: list,
    chunk_size_tokens: int,
    overlap_tokens: int,
    embedder=None,
    similarity_threshold: float = 0.5,
) -> list[Chunk]:
    if embedder is None:
        raise ValueError("semantic chunking requires an embedder instance")

    chunks: list[Chunk] = []
    index = 0
    max_chars = chunk_size_tokens * 4

    for page in pages:
        sentences = _split_sentences(page.text)
        if not sentences:
            continue
        if len(sentences) == 1:
            chunks.append(
                Chunk(
                    chunk_index=index,
                    text=sentences[0],
                    page=page.page_number,
                    section=None,
                    token_count=estimate_tokens(sentences[0]),
                )
            )
            index += 1
            continue

        vectors = np.array(embedder.embed_documents(sentences), dtype=np.float32)
        # Embeddings are L2-normalized at source (see LocalEmbedder), so dot product
        # between consecutive rows is cosine similarity.
        similarities = np.sum(vectors[:-1] * vectors[1:], axis=1)

        buffer_sentences = [sentences[0]]
        buffer_len = len(sentences[0])
        for i in range(1, len(sentences)):
            sentence = sentences[i]
            candidate_len = buffer_len + 1 + len(sentence)
            topic_break = similarities[i - 1] < similarity_threshold
            size_break = candidate_len > max_chars

            if topic_break or size_break:
                chunk_text = " ".join(buffer_sentences)
                chunks.append(
                    Chunk(
                        chunk_index=index,
                        text=chunk_text,
                        page=page.page_number,
                        section=None,
                        token_count=estimate_tokens(chunk_text),
                    )
                )
                index += 1
                overlap_sentences = _tail_sentences(buffer_sentences, overlap_tokens * 4)
                buffer_sentences = [*overlap_sentences, sentence]
                buffer_len = sum(len(s) for s in buffer_sentences) + len(buffer_sentences) - 1
            else:
                buffer_sentences.append(sentence)
                buffer_len = candidate_len

        if buffer_sentences:
            chunk_text = " ".join(buffer_sentences)
            chunks.append(
                Chunk(
                    chunk_index=index,
                    text=chunk_text,
                    page=page.page_number,
                    section=None,
                    token_count=estimate_tokens(chunk_text),
                )
            )
            index += 1

    return chunks


def _tail_sentences(sentences: list[str], max_overlap_chars: int) -> list[str]:
    """Carry the last few sentences forward as overlap, staying under the char budget."""
    if max_overlap_chars <= 0:
        return []
    tail: list[str] = []
    used = 0
    for sentence in reversed(sentences):
        if used + len(sentence) > max_overlap_chars:
            break
        tail.insert(0, sentence)
        used += len(sentence) + 1
    return tail
