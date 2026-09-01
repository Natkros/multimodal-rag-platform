from __future__ import annotations

from app.models.db import Document, get_session_factory
from app.repositories.document_repository import DocumentRepository
from app.services.ingestion.pipeline import run_ingestion


def _make_document(db, filename: str, file_type: str, file_hash: str) -> Document:
    repo = DocumentRepository(db)
    return repo.create(
        Document(filename=filename, file_type=file_type, file_hash=file_hash, processing_status="UPLOADED")
    )


def test_run_ingestion_indexes_text_document(test_settings):
    session_factory = get_session_factory()
    from app.models.db import init_db

    init_db()
    db = session_factory()
    doc = _make_document(db, "notes.txt", "txt", "hash-1")
    document_id = doc.document_id
    db.close()

    content = ("Acme's revenue grew 20% in 2025. " * 20).encode("utf-8")
    run_ingestion(document_id, "txt", content, "notes.txt", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count >= 1
    chunks = repo.get_chunks(document_id)
    assert len(chunks) == refreshed.chunk_count
    assert all(c.vector_id for c in chunks)
    db.close()


def test_run_ingestion_marks_failed_on_corrupted_pdf(test_settings):
    from app.models.db import init_db

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "broken.pdf", "pdf", "hash-2")
    document_id = doc.document_id
    db.close()

    run_ingestion(document_id, "pdf", b"not a real pdf", "broken.pdf", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "FAILED"
    assert refreshed.error_message
    db.close()


def test_run_ingestion_end_to_end_retrievable(test_settings):
    from app.models.db import init_db
    from app.services.embeddings.factory import get_embedder
    from app.services.retrieval.factory import get_vector_store
    from app.services.retrieval.retriever import DenseRetriever

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "revenue.txt", "txt", "hash-3")
    document_id = doc.document_id
    db.close()

    content = ("Acme's Q2 2025 revenue was $42.3 million, up 18% year over year. " * 5).encode("utf-8")
    run_ingestion(document_id, "txt", content, "revenue.txt", test_settings)

    embedder = get_embedder(test_settings)
    vector_store = get_vector_store(test_settings, embedder.dimension)
    retriever = DenseRetriever(embedder=embedder, vector_store=vector_store)

    results = retriever.retrieve("What was Acme's Q2 2025 revenue?", top_k=3)
    assert len(results) >= 1
    assert results[0].document_id == document_id
    assert "42.3 million" in results[0].text
