#!/usr/bin/env python
"""Phase 6 experiment: measure dense-only vs. hybrid (dense + BM25) retrieval.

Unlike scripts/compare_chunking_strategies.py, this reuses the exact-chunk_id-based
metrics from app/services/evaluation/retrieval_metrics.py (Recall@K, Precision@K, MRR,
nDCG against `expected_chunks`) rather than content-based substring matching — dense
vs. hybrid doesn't change where chunk boundaries fall (same CHUNKING_STRATEGY, same
chunk_ids), only how those same chunks get ranked, so the Phase 1 ground truth stays
valid across both modes.

Each mode gets its own isolated DB/vector-store/sparse-index (same isolation pattern
as compare_chunking_strategies.py) so results can't leak between runs.

Usage:
    python scripts/compare_retrieval_modes.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

MODES = ["dense", "hybrid"]


def _reset_for_mode(mode: str, scratch_root: Path):
    mode_dir = scratch_root / mode
    if mode_dir.exists():
        shutil.rmtree(mode_dir)
    mode_dir.mkdir(parents=True)

    os.environ["DATABASE_URL"] = f"sqlite:///{mode_dir / 'retrieval_experiment.db'}"
    os.environ["DATA_DIR"] = str(mode_dir)
    os.environ["UPLOAD_DIR"] = str(mode_dir / "uploads")
    os.environ["LOCAL_VECTOR_STORE_DIR"] = str(mode_dir / "vector_store")
    os.environ["LOCAL_SPARSE_INDEX_DIR"] = str(mode_dir / "sparse_index")
    os.environ["VECTOR_STORE"] = "local"
    os.environ["EMBEDDING_PROVIDER"] = "local"
    os.environ["CHUNKING_STRATEGY"] = "recursive"  # held fixed — only RETRIEVAL_MODE varies
    os.environ["RETRIEVAL_MODE"] = mode

    import app.models.db as db_module
    from app.core.config import get_settings
    from app.services.embeddings.local_embedder import get_local_embedder
    from app.services.retrieval.factory import _cached_local_store, _cached_sparse_index

    get_settings.cache_clear()
    get_local_embedder.cache_clear()
    _cached_local_store.cache_clear()
    _cached_sparse_index.cache_clear()
    db_module._engine = None
    db_module._SessionLocal = None

    return get_settings()


def run_one_mode(mode: str, dataset: list[dict], corpus_dir: Path, scratch_root: Path, top_k: int) -> dict:
    settings = _reset_for_mode(mode, scratch_root)

    import run_eval

    from app.services.embeddings.factory import get_embedder
    from app.services.evaluation.retrieval_metrics import aggregate_metrics
    from app.services.retrieval.factory import get_retriever, get_vector_store

    ingest_start = time.perf_counter()
    run_eval.ingest_corpus(corpus_dir)
    ingest_time_s = time.perf_counter() - ingest_start

    embedder = get_embedder(settings)
    vector_store = get_vector_store(settings, embedder.dimension)
    retriever = get_retriever(settings, embedder, vector_store)

    per_query_retrieved: list[list[str]] = []
    per_query_relevant: list[set[str]] = []
    latencies_ms: list[float] = []

    for case in dataset:
        start = time.perf_counter()
        results = retriever.retrieve(case["question"], top_k=top_k)
        latencies_ms.append((time.perf_counter() - start) * 1000)
        per_query_retrieved.append([r.chunk_id for r in results])
        per_query_relevant.append(set(case.get("expected_chunks", [])))

    metrics = aggregate_metrics(per_query_retrieved, per_query_relevant)
    metrics["latency_p50_ms"] = round(sorted(latencies_ms)[len(latencies_ms) // 2] if latencies_ms else 0, 3)
    metrics["latency_p95_ms"] = round(
        sorted(latencies_ms)[int(len(latencies_ms) * 0.95)] if latencies_ms else 0, 3
    )
    metrics["ingest_time_s"] = round(ingest_time_s, 2)
    return metrics


def main() -> None:
    import run_eval

    dataset_path = Path("evaluation/datasets/qa_dataset.jsonl")
    corpus_dir = Path("sample_docs")
    scratch_root = Path("data/retrieval_mode_experiments")
    top_k = 5

    dataset = run_eval.load_dataset(dataset_path)
    results = {}
    for mode in MODES:
        print(f"\n=== Ingesting + evaluating retrieval_mode={mode} ===")
        results[mode] = run_one_mode(mode, dataset, corpus_dir, scratch_root, top_k)
        print(json.dumps(results[mode], indent=2))

    report_dir = Path("evaluation/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"retrieval_mode_comparison_{timestamp}.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n\n| Mode   | Recall@5 | Recall@10 | MRR   | nDCG@5 | Latency p50 (ms) |")
    print("|--------|---------:|----------:|------:|-------:|-----------------:|")
    for mode in MODES:
        m = results[mode]
        print(
            f"| {mode:<6} | {m.get('recall@5', 0):.3f}    | {m.get('recall@10', 0):.3f}     "
            f"| {m.get('mrr', 0):.3f} | {m.get('ndcg@5', 0):.3f}  | {m.get('latency_p50_ms', 0):>16.2f} |"
        )
    print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
