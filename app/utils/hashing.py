from __future__ import annotations

import hashlib
import uuid
from pathlib import PureWindowsPath

_DOCUMENT_ID_NAMESPACE = uuid.UUID("2f6f9d1a-2f2b-4e63-9c4c-6e0e6a3b0a11")


def deterministic_document_id(file_hash: str) -> str:
    """Derive a stable document_id from content hash so re-ingesting the same file in a
    fresh environment (e.g. the eval harness) reproduces the same chunk_ids — required
    for `expected_chunks` in evaluation/datasets/qa_dataset.jsonl to stay valid."""
    return str(uuid.uuid5(_DOCUMENT_ID_NAMESPACE, file_hash))


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def classify_file_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mapping = {
        "pdf": "pdf",
        "txt": "txt",
        "md": "markdown",
        "markdown": "markdown",
        "docx": "docx",
        "html": "html",
        "htm": "html",
        "png": "image",
        "jpg": "image",
        "jpeg": "image",
    }
    return mapping.get(ext, "unknown")


def safe_filename(raw: str) -> str:
    """Strip any directory components from a user-supplied filename before it's used
    to build a filesystem path (upload_dir writes/reads in
    app/api/routes/documents.py). `PureWindowsPath` splits on both `/` and `\\`
    regardless of host OS, so this defends against `../../etc/passwd`-style and
    `..\\..\\evil.txt`-style traversal the same way whether the app runs on Linux
    (Docker/prod) or Windows (local dev) — the raw filename is still stored verbatim
    in the database for display, only the on-disk path uses this sanitized form."""
    name = PureWindowsPath(raw or "").name
    if not name or name in (".", ".."):
        return "unnamed"
    return name
