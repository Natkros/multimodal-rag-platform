from __future__ import annotations

import hashlib
import uuid

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
