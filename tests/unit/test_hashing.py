from __future__ import annotations

from app.utils.hashing import classify_file_type, safe_filename, sha256_bytes


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


def test_safe_filename_strips_unix_style_path_traversal():
    assert safe_filename("../../../../etc/passwd") == "passwd"


def test_safe_filename_strips_windows_style_path_traversal():
    assert safe_filename("..\\..\\..\\windows\\system32\\evil.dll") == "evil.dll"


def test_safe_filename_strips_absolute_path():
    assert safe_filename("/etc/cron.d/evil") == "evil"
    assert safe_filename("C:\\Windows\\evil.exe") == "evil.exe"


def test_safe_filename_rejects_dot_and_dotdot():
    assert safe_filename("..") == "unnamed"
    assert safe_filename(".") == "unnamed"


def test_safe_filename_rejects_empty_or_none():
    assert safe_filename("") == "unnamed"
    assert safe_filename(None) == "unnamed"


def test_safe_filename_leaves_ordinary_filename_untouched():
    assert safe_filename("report_final_v2.pdf") == "report_final_v2.pdf"
