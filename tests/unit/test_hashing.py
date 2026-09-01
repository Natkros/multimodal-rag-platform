from __future__ import annotations

from app.utils.hashing import classify_file_type, sha256_bytes


def test_sha256_bytes_is_deterministic():
    assert sha256_bytes(b"hello") == sha256_bytes(b"hello")


def test_sha256_bytes_differs_for_different_content():
    assert sha256_bytes(b"hello") != sha256_bytes(b"world")


def test_sha256_bytes_has_prefix():
    assert sha256_bytes(b"hello").startswith("sha256:")


def test_classify_file_type_known_extensions():
    assert classify_file_type("report.pdf") == "pdf"
    assert classify_file_type("notes.md") == "markdown"
    assert classify_file_type("readme.txt") == "txt"
    assert classify_file_type("scan.png") == "image"


def test_classify_file_type_unknown_extension():
    assert classify_file_type("archive.zip") == "unknown"


def test_classify_file_type_no_extension():
    assert classify_file_type("Makefile") == "unknown"
