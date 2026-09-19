#!/usr/bin/env python
"""Phase 20 performance engineering: times each real ingestion stage
(extraction -> embedder load -> chunking -> embedding -> indexing) for every
document in sample_docs, plus retrieval/generation stage latency by reusing
scripts/run_eval.py's dense-baseline report. Answers "where does the time actually
go" with real numbers, not assumed bottlenecks — see
docs/decisions/0020-phase20-performance.md for the results and what was/wasn't
optimized as a result.

Usage:
    python scripts/profile_pipeline.py --corpus sample_docs
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.services.embeddings.factory import get_embedder
from app.services.extraction.loaders import extract
from app.services.ingestion.pipeline import _build_chunks
from app.services.retrieval.factory import get_sparse_index, get_vector_store
from app.services.retrieval.sparse_index import SparseRecord
from app.services.retrieval.vector_store import VectorRecord
from app.utils.hashing import classify_file_type


def profile_document(path: Path, settings) -> dict:
    raw_bytes = path.read_bytes()
    file_type = classify_file_type(path.name)
    timings = {}

    start = time.perf_counter()
    extraction = extract(file_type, raw_bytes, settings)
    timings["extraction_ms"] = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    embedder = get_embedder(settings)
    timings["embedder_load_ms"] = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    chunks = _build_chunks(extraction, file_type, raw_bytes, settings, embedder)
    timings["chunking_ms"] = (time.perf_counter() - start) * 1000

    if not chunks:
        timings["embedding_ms"] = 0.0
        timings["indexing_ms"] = 0.0
        timings["n_chunks"] = 0
        return {"file": path.name, "file_type": file_type, **timings}

    start = time.perf_counter()
    texts = [c.text for c in chunks]
    vectors = embedder.embed_documents(texts)
    timings["embedding_ms"] = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    vector_store = get_vector_store(settings, embedder.dimension)
    doc_id = f"profile-{path.stem}"
    vector_records = [
        VectorRecord(vector_id=f"{doc_id}::chunk-{c.chunk_index}", values=v, metadata={"document_id": doc_id})
        for c, v in zip(chunks, vectors, strict=True)
    ]
    sparse_records = [
        SparseRecord(doc_id=f"{doc_id}::chunk-{c.chunk_index}", text=c.text, metadata={"document_id": doc_id})
        for c in chunks
    ]
    vector_store.upsert(vector_records)
    get_sparse_index(settings).upsert(sparse_records)
    timings["indexing_ms"] = (time.perf_counter() - start) * 1000

    timings["n_chunks"] = len(chunks)
    return {"file": path.name, "file_type": file_type, **timings}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("sample_docs"))
    args = parser.parse_args()

    settings = get_settings()
    results = []
    for path in sorted(args.corpus.iterdir()):
        if not path.is_file():
            continue
        file_type = classify_file_type(path.name)
        if file_type not in settings.allowed_file_types:
            continue
        print(f"profiling: {path.name}")
        results.append(profile_document(path, settings))

    stage_totals = {}
    for r in results:
        for key in ("extraction_ms", "embedder_load_ms", "chunking_ms", "embedding_ms", "indexing_ms"):
            stage_totals[key] = stage_totals.get(key, 0.0) + r[key]

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "per_document": results,
        "stage_totals_ms": {k: round(v, 2) for k, v in stage_totals.items()},
    }
    print(json.dumps(report, indent=2))

    out_dir = Path("evaluation/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ingestion_profile_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
