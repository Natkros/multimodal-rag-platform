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


def test_run_ingestion_catalogs_blank_image_without_chunking(test_settings):
    """A blank image has no OCR text and, with no vision LLM configured, no caption
    either — it should still be cataloged (Phase 2 behavior), not fail."""
    from io import BytesIO

    from PIL import Image

    from app.models.db import init_db

    init_db()
    test_settings.vision_description_enabled = False
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "blank.png", "image", "hash-blank-image")
    document_id = doc.document_id
    db.close()

    img = Image.new("RGB", (50, 50), "gray")
    buf = BytesIO()
    img.save(buf, format="PNG")
    run_ingestion(document_id, "image", buf.getvalue(), "blank.png", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count == 0
    assert refreshed.metadata_json["image_width"] == 50
    assert repo.get_chunks(document_id) == []
    db.close()


def test_run_ingestion_ocrs_image_with_text(test_settings, sample_docs_dir):
    """The sample revenue chart has real drawn text (title, axis labels, $ values) —
    with Tesseract installed, OCR should make it searchable without needing an LLM."""
    from app.models.db import init_db
    from app.services.extraction.ocr import is_ocr_available

    init_db()
    if not is_ocr_available(test_settings):
        import pytest

        pytest.skip("Tesseract not installed")

    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "chart.png", "image", "hash-image-ocr")
    document_id = doc.document_id
    db.close()

    raw = (sample_docs_dir / "acme_quarterly_revenue_chart.png").read_bytes()
    run_ingestion(document_id, "image", raw, "chart.png", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count == 1
    chunks = repo.get_chunks(document_id)
    assert chunks[0].content_type == "image"
    assert chunks[0].extra_metadata["ocr_text"]
    assert chunks[0].vector_id  # embedded and indexed, unlike Phase 2's catalog-only images
    db.close()


def test_run_ingestion_captions_image_via_vision_llm_when_ocr_finds_nothing(test_settings, monkeypatch):
    """A photo-like image with no text: OCR finds nothing, so the pipeline should try
    a vision-LLM caption instead and index that."""
    from io import BytesIO

    from PIL import Image

    from app.models.db import init_db

    init_db()

    def fake_describe_image(raw_bytes, image_format, settings):
        return "A stock photo of a mountain landscape at sunset."

    monkeypatch.setattr("app.services.ingestion.pipeline.describe_image", fake_describe_image)

    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "landscape.png", "image", "hash-image-caption")
    document_id = doc.document_id
    db.close()

    img = Image.new("RGB", (80, 60), "orange")
    buf = BytesIO()
    img.save(buf, format="PNG")
    run_ingestion(document_id, "image", buf.getvalue(), "landscape.png", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count == 1
    chunks = repo.get_chunks(document_id)
    assert chunks[0].content_type == "image"
    assert "mountain" in chunks[0].text.lower()
    assert chunks[0].extra_metadata["caption"] == "A stock photo of a mountain landscape at sunset."
    db.close()


def test_run_ingestion_extracts_docx_table_as_structured_chunk(test_settings, sample_docs_dir):
    from app.models.db import init_db

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "policy2.docx", "docx", "hash-docx-table")
    document_id = doc.document_id
    db.close()

    raw = (sample_docs_dir / "acme_vendor_security_policy.docx").read_bytes()
    run_ingestion(document_id, "docx", raw, "policy2.docx", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    table_chunks = [c for c in repo.get_chunks(document_id) if c.content_type == "table"]
    assert len(table_chunks) >= 1
    assert table_chunks[0].extra_metadata["headers"]
    assert table_chunks[0].extra_metadata["rows"]
    assert table_chunks[0].vector_id  # tables are embedded/indexed like any other chunk
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


def test_run_ingestion_with_semantic_strategy(test_settings):
    from app.models.db import init_db

    init_db()
    test_settings.chunking_strategy = "semantic"
    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "topics.txt", "txt", "hash-semantic")
    document_id = doc.document_id
    db.close()

    content = (
        b"Acme's revenue grew significantly in the second quarter. Revenue reached "
        b"42.3 million dollars, an increase of 18 percent year over year. "
        b"In unrelated news, the office cafeteria introduced a new vegetarian menu. "
        b"Employees have responded positively to the expanded lunch options."
    )
    run_ingestion(document_id, "txt", content, "topics.txt", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count >= 1
    assert refreshed.metadata_json.get("indexed_with_chunking_strategy") == "semantic"
    db.close()


def test_run_ingestion_ocrs_scanned_pdf(test_settings, sample_docs_dir):
    from app.models.db import init_db
    from app.services.extraction.ocr import is_ocr_available

    init_db()
    if not is_ocr_available(test_settings):
        import pytest

        pytest.skip("Tesseract/Poppler not installed")

    session_factory = get_session_factory()
    db = session_factory()
    doc = _make_document(db, "expense_notice.pdf", "pdf", "hash-scanned-pdf")
    document_id = doc.document_id
    db.close()

    raw = (sample_docs_dir / "acme_expense_notice_scanned.pdf").read_bytes()
    run_ingestion(document_id, "pdf", raw, "expense_notice.pdf", test_settings)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count >= 1
    assert refreshed.metadata_json.get("ocr_used") is True
    chunks = repo.get_chunks(document_id)
    assert any("ER-20458" in c.text or "expense" in c.text.lower() for c in chunks)
    db.close()
