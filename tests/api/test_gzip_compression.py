from __future__ import annotations


def test_large_response_is_gzip_compressed(client):
    """GZipMiddleware (Phase 20) only compresses responses at/above minimum_size
    (1000 bytes). GET /documents/{id}/chunks returns full chunk text (unlike
    /query's response, which only carries chunk_ids/scores - see
    app/schemas/query.py's SourceRef), so a large-enough upload reliably clears
    that bar. Confirms the server actually negotiated gzip rather than just
    accepting the header - httpx's TestClient auto-decompresses transparently, so
    this checks the raw transport header rather than trying to compare payload
    sizes through a client that already undoes the compression."""
    content = ("Acme Corporation was founded in 2010 in Austin, Texas. " * 200).encode("utf-8")
    upload_resp = client.post("/documents/upload", files={"file": ("big.txt", content, "text/plain")})
    document_id = upload_resp.json()["document_id"]

    resp = client.get(f"/documents/{document_id}/chunks", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"


def test_small_response_is_not_gzip_compressed(client):
    """Below GZipMiddleware's minimum_size, compressing would add framing overhead
    for no size benefit - confirms the threshold is real, not a no-op."""
    resp = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") != "gzip"
