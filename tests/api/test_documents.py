from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_upload_txt_document_gets_indexed(client, sample_docs_dir: Path):
    content = "Acme was founded in 2010. Acme's headquarters are in Austin, Texas."
    files = {"file": ("company_facts.txt", content.encode("utf-8"), "text/plain")}
    resp = client.post("/documents/upload", files=files)
    assert resp.status_code == 202
    body = resp.json()
    assert body["filename"] == "company_facts.txt"
    assert body["file_type"] == "txt"

    document_id = body["document_id"]
    get_resp = client.get(f"/documents/{document_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["processing_status"] == "INDEXED"
    assert get_resp.json()["chunk_count"] >= 1


def test_upload_duplicate_returns_409(client):
    content = b"Duplicate detection test content."
    files = {"file": ("dup.txt", content, "text/plain")}
    first = client.post("/documents/upload", files=files)
    assert first.status_code == 202

    second = client.post("/documents/upload", files={"file": ("dup2.txt", content, "text/plain")})
    assert second.status_code == 409


def test_upload_unsupported_file_type_rejected(client):
    resp = client.post(
        "/documents/upload", files={"file": ("archive.zip", b"PK\x03\x04", "application/zip")}
    )
    assert resp.status_code == 400


def test_upload_empty_file_rejected(client):
    resp = client.post("/documents/upload", files={"file": ("empty.txt", b"", "text/plain")})
    assert resp.status_code == 400


def test_upload_with_rq_backend_enqueues_instead_of_running_in_process(client, test_settings, monkeypatch):
    """JOB_QUEUE_BACKEND=rq should call enqueue_ingestion instead of
    BackgroundTasks.add_task — verified by mocking enqueue_ingestion rather than
    requiring a real Redis (that path is covered end-to-end, with a real Redis and a
    real RQ worker, by tests/integration/test_job_queue_rq.py, skipped when no Redis
    is reachable). Since the job is never actually processed here (the mock is a
    no-op), the document correctly stays UPLOADED, not INDEXED."""
    import app.api.routes.documents as documents_module

    monkeypatch.setattr(test_settings, "job_queue_backend", "rq")
    mock_enqueue = MagicMock()
    monkeypatch.setattr(documents_module, "enqueue_ingestion", mock_enqueue)

    resp = client.post(
        "/documents/upload", files={"file": ("rq_test.txt", b"Acme facts for RQ routing test.", "text/plain")}
    )
    assert resp.status_code == 202
    document_id = resp.json()["document_id"]

    mock_enqueue.assert_called_once()
    args = mock_enqueue.call_args[0]
    assert args[0] == document_id
    assert args[1] == "txt"

    get_resp = client.get(f"/documents/{document_id}")
    assert get_resp.json()["processing_status"] == "UPLOADED"


def test_list_documents_empty_initially(client):
    resp = client.get("/documents")
    assert resp.status_code == 200
    assert resp.json() == {"documents": [], "total": 0}


def test_get_nonexistent_document_404(client):
    resp = client.get("/documents/does-not-exist")
    assert resp.status_code == 404


def test_delete_document(client):
    files = {"file": ("to_delete.txt", b"Some content to delete later.", "text/plain")}
    upload = client.post("/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    delete_resp = client.delete(f"/documents/{document_id}")
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/documents/{document_id}")
    assert get_resp.status_code == 404


def test_delete_document_cleans_up_sparse_index(client, test_settings):
    from app.services.retrieval.factory import get_sparse_index

    files = {"file": ("to_delete2.txt", b"Distinctive gizmo widget content here.", "text/plain")}
    upload = client.post("/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    sparse_index = get_sparse_index(test_settings)
    assert sparse_index.query("gizmo widget", top_k=5)

    client.delete(f"/documents/{document_id}")
    assert sparse_index.query("gizmo widget", top_k=5) == []


def test_upload_markdown_and_pdf_from_sample_docs(client, sample_docs_dir: Path):
    md_path = sample_docs_dir / "acme_employee_handbook.md"
    with md_path.open("rb") as f:
        resp = client.post(
            "/documents/upload", files={"file": (md_path.name, f, "text/markdown")}
        )
    assert resp.status_code == 202
    assert resp.json()["file_type"] == "markdown"

    pdf_path = sample_docs_dir / "attention_is_all_you_need.pdf"
    with pdf_path.open("rb") as f:
        resp = client.post(
            "/documents/upload", files={"file": (pdf_path.name, f, "application/pdf")}
        )
    assert resp.status_code == 202
    assert resp.json()["file_type"] == "pdf"

    doc_id = resp.json()["document_id"]
    detail = client.get(f"/documents/{doc_id}").json()
    assert detail["processing_status"] == "INDEXED"
    assert detail["page_count"] and detail["page_count"] > 1


def test_upload_docx_gets_indexed(client, sample_docs_dir: Path):
    path = sample_docs_dir / "acme_vendor_security_policy.docx"
    with path.open("rb") as f:
        resp = client.post(
            "/documents/upload",
            files={"file": (path.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert resp.status_code == 202
    assert resp.json()["file_type"] == "docx"

    doc_id = resp.json()["document_id"]
    detail = client.get(f"/documents/{doc_id}").json()
    assert detail["processing_status"] == "INDEXED"
    assert detail["chunk_count"] >= 1


def test_upload_html_gets_indexed(client, sample_docs_dir: Path):
    path = sample_docs_dir / "roomwise_product_faq.html"
    with path.open("rb") as f:
        resp = client.post("/documents/upload", files={"file": (path.name, f, "text/html")})
    assert resp.status_code == 202
    assert resp.json()["file_type"] == "html"

    doc_id = resp.json()["document_id"]
    detail = client.get(f"/documents/{doc_id}").json()
    assert detail["processing_status"] == "INDEXED"
    assert detail["chunk_count"] >= 1


def test_upload_image_with_text_is_ocrd_and_searchable(client, sample_docs_dir: Path):
    """The sample chart has real drawn text (title, axis labels), so with Tesseract
    installed it should be OCR'd and indexed rather than merely cataloged."""
    from app.core.config import get_settings
    from app.services.extraction.ocr import is_ocr_available

    path = sample_docs_dir / "acme_quarterly_revenue_chart.png"
    with path.open("rb") as f:
        resp = client.post("/documents/upload", files={"file": (path.name, f, "image/png")})
    assert resp.status_code == 202
    assert resp.json()["file_type"] == "image"

    doc_id = resp.json()["document_id"]
    detail = client.get(f"/documents/{doc_id}").json()
    assert detail["processing_status"] == "INDEXED"

    if is_ocr_available(get_settings()):
        assert detail["chunk_count"] == 1
    else:
        assert detail["chunk_count"] == 0  # no OCR, no vision LLM in tests -> catalog-only


def test_upload_blank_image_is_cataloged_without_chunks(client):
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (40, 40), "gray")
    buf = BytesIO()
    img.save(buf, format="PNG")

    resp = client.post("/documents/upload", files={"file": ("blank.png", buf.getvalue(), "image/png")})
    assert resp.status_code == 202
    doc_id = resp.json()["document_id"]
    detail = client.get(f"/documents/{doc_id}").json()
    assert detail["processing_status"] == "INDEXED"
    assert detail["chunk_count"] == 0  # no OCR text, no vision LLM configured in tests


def test_get_chunks_for_document(client):
    files = {"file": ("facts.txt", b"Acme was founded in Austin in 2010. " * 5, "text/plain")}
    upload = client.post("/documents/upload", files=files)
    doc_id = upload.json()["document_id"]

    resp = client.get(f"/documents/{doc_id}/chunks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert body["chunks"][0]["content_type"] == "text"
    assert "Austin" in body["chunks"][0]["text"]


def test_get_chunks_for_docx_includes_table_chunk(client, sample_docs_dir: Path):
    path = sample_docs_dir / "acme_vendor_security_policy.docx"
    with path.open("rb") as f:
        upload = client.post("/documents/upload", files={"file": (path.name, f, "application/octet-stream")})
    doc_id = upload.json()["document_id"]

    resp = client.get(f"/documents/{doc_id}/chunks")
    assert resp.status_code == 200
    content_types = {c["content_type"] for c in resp.json()["chunks"]}
    assert "table" in content_types
    table_chunk = next(c for c in resp.json()["chunks"] if c["content_type"] == "table")
    assert table_chunk["extra_metadata"]["headers"]


def test_get_chunks_for_nonexistent_document_404(client):
    resp = client.get("/documents/does-not-exist/chunks")
    assert resp.status_code == 404


def test_check_staleness_flags_nothing_when_config_unchanged(client, sample_docs_dir: Path):
    path = sample_docs_dir / "acme_vendor_security_policy.docx"
    with path.open("rb") as f:
        client.post("/documents/upload", files={"file": (path.name, f, "application/octet-stream")})

    resp = client.post("/documents/check-staleness")
    assert resp.status_code == 200
    assert resp.json() == {"flagged_document_ids": [], "count": 0}
