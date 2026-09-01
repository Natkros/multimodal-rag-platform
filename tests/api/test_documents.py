from __future__ import annotations

from pathlib import Path


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
