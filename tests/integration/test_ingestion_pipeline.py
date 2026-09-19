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


def test_run_ingestion_indexes_docx(test_settings, sample_docs_dir):
    from app.models.db import init_db

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "policy.docx", "docx", "hash-docx")
    document_id = doc.document_id
    db.close()

    raw = (sample_docs_dir / "acme_vendor_security_policy.docx").read_bytes()
    run_ingestion(document_id, "docx", raw, "policy.docx", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count >= 1
    assert refreshed.metadata_json.get("title") == "Acme Vendor Security Policy"
    db.close()


def test_run_ingestion_indexes_html(test_settings, sample_docs_dir):
    from app.models.db import init_db

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "faq.html", "html", "hash-html")
    document_id = doc.document_id
    db.close()

    raw = (sample_docs_dir / "roomwise_product_faq.html").read_bytes()
    run_ingestion(document_id, "html", raw, "faq.html", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count >= 1
    db.close()


def test_run_ingestion_catalogs_image_without_chunking(test_settings, sample_docs_dir):
    from app.models.db import init_db

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "chart.png", "image", "hash-image")
    document_id = doc.document_id
    db.close()

    raw = (sample_docs_dir / "acme_quarterly_revenue_chart.png").read_bytes()
    run_ingestion(document_id, "image", raw, "chart.png", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count == 0
    assert refreshed.metadata_json["image_width"] > 0
    assert refreshed.metadata_json["text_extraction"] == "pending_multimodal_processing"
    assert repo.get_chunks(document_id) == []
    db.close()


def test_staleness_flags_documents_indexed_under_old_config(test_settings, sample_docs_dir):
    from app.models.db import init_db
    from app.services.ingestion.staleness import find_and_flag_stale_documents

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "notes.txt", "txt", "hash-stale")
    document_id = doc.document_id
    db.close()

    run_ingestion(document_id, "txt", b"Some indexable content here. " * 10, "notes.txt", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    assert repo.get(document_id).processing_status == "INDEXED"

    # No config change yet -> nothing should be flagged.
    assert find_and_flag_stale_documents(repo, test_settings) == []

    # Simulate a config change (e.g. chunking strategy switched in settings).
    test_settings.chunking_strategy = "fixed"
    flagged = find_and_flag_stale_documents(repo, test_settings)
    assert flagged == [document_id]
    assert repo.get(document_id).processing_status == "REINDEX_REQUIRED"
    db.close()
