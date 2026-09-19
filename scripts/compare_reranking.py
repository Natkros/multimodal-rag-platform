#!/usr/bin/env python
"""Phase 7 experiment: measure hybrid retrieval with vs. without cross-encoder
reranking. Per the project rule ("do not assume reranking improves the system;
prove it experimentally"), this produces a real before/after number rather than
asserting the reranker helps.

Holds RETRIEVAL_MODE=hybrid fixed (Phase 6's best-measured mode) and only varies
RERANKER_ENABLED, so any delta is attributable to reranking alone. Like
scripts/compare_retrieval_modes.py, reranking doesn't move chunk boundaries — same
chunk_ids either way — so this reuses the exact chunk_id-based
app/services/evaluation/retrieval_metrics.py rather than Phase 3's content-based
metrics.

Usage:
    python scripts/compare_reranking.py
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

CONFIGS = [
    {"name": "hybrid_no_rerank", "reranker_enabled": "false"},
    {"name": "hybrid_with_rerank", "reranker_enabled": "true"},
]
CANDIDATE_POOL = 30
FINAL_TOP_K = 5


def _reset_for_config(name: str, reranker_enabled: str, scratch_root: Path):
    config_dir = scratch_root / name
    if config_dir.exists():
        shutil.rmtree(config_dir)
    config_dir.mkdir(parents=True)

    os.environ["DATABASE_URL"] = f"sqlite:///{config_dir / 'rerank_experiment.db'}"
    os.environ["DATA_DIR"] = str(config_dir)
    os.environ["UPLOAD_DIR"] = str(config_dir / "uploads")
    os.environ["LOCAL_VECTOR_STORE_DIR"] = str(config_dir / "vector_store")
    os.environ["LOCAL_SPARSE_INDEX_DIR"] = str(config_dir / "sparse_index")
    os.environ["VECTOR_STORE"] = "local"
    os.environ["EMBEDDING_PROVIDER"] = "local"
    os.environ["CHUNKING_STRATEGY"] = "recursive"
    os.environ["RETRIEVAL_MODE"] = "hybrid"  # Phase 6's best-measured mode, held fixed
    os.environ["RERANKER_ENABLED"] = reranker_enabled
    os.environ["RERANK_CANDIDATE_POOL"] = str(CANDIDATE_POOL)

    import app.models.db as db_module
    from app.core.config import get_settings
    from app.services.embeddings.local_embedder import get_local_embedder
    from app.services.reranking.reranker import _cached_reranker
    from app.services.retrieval.factory import _cached_local_store, _cached_sparse_index

    get_settings.cache_clear()
    get_local_embedder.cache_clear()
    _cached_local_store.cache_clear()
    _cached_sparse_index.cache_clear()
    _cached_reranker.cache_clear()
    db_module._engine = None
    db_module._SessionLocal = None

    return get_settings()


def run_one_config(config: dict, dataset: list[dict], corpus_dir: Path, scratch_root: Path) -> dict:
    settings = _reset_for_config(config["name"], config["reranker_enabled"], scratch_root)

    import run_eval

    from app.services.embeddings.factory import get_embedder
    from app.services.evaluation.retrieval_metrics import aggregate_metrics
    from app.services.reranking.reranker import get_reranker
    from app.services.retrieval.factory import get_retriever, get_vector_store

    run_eval.ingest_corpus(corpus_dir)

    embedder = get_embedder(settings)
    vector_store = get_vector_store(settings, embedder.dimension)
    retriever = get_retriever(settings, embedder, vector_store)
    reranker = get_reranker(settings) if settings.reranker_enabled else None

    per_query_retrieved: list[list[str]] = []
    per_query_relevant: list[set[str]] = []
    retrieval_latencies_ms: list[float] = []
    rerank_latencies_ms: list[float] = []

    for case in dataset:
        pool_k = CANDIDATE_POOL if reranker else FINAL_TOP_K
        start = time.perf_counter()
        candidates = retriever.retrieve(case["question"], top_k=pool_k)
        retrieval_latencies_ms.append((time.perf_counter() - start) * 1000)

        if reranker:
            start = time.perf_counter()
            final = reranker.rerank(case["question"], candidates, top_k=FINAL_TOP_K)
            rerank_latencies_ms.append((time.perf_counter() - start) * 1000)
        else:
            final = candidates[:FINAL_TOP_K]

        per_query_retrieved.append([c.chunk_id for c in final])
        per_query_relevant.append(set(case.get("expected_chunks", [])))

    metrics = aggregate_metrics(per_query_retrieved, per_query_relevant)
    metrics["retrieval_latency_p50_ms"] = round(
        sorted(retrieval_latencies_ms)[len(retrieval_latencies_ms) // 2] if retrieval_latencies_ms else 0, 3
    )
    if rerank_latencies_ms:
        metrics["rerank_latency_p50_ms"] = round(
            sorted(rerank_latencies_ms)[len(rerank_latencies_ms) // 2], 3
        )
        metrics["total_latency_p50_ms"] = round(
            metrics["retrieval_latency_p50_ms"] + metrics["rerank_latency_p50_ms"], 3
        )
    else:
        metrics["rerank_latency_p50_ms"] = 0.0
        metrics["total_latency_p50_ms"] = metrics["retrieval_latency_p50_ms"]
    return metrics


def main() -> None:
    import run_eval

    dataset_path = Path("evaluation/datasets/qa_dataset.jsonl")
    corpus_dir = Path("sample_docs")
    scratch_root = Path("data/reranking_experiments")

    dataset = run_eval.load_dataset(dataset_path)
    results = {}
    for config in CONFIGS:
        print(f"\n=== Evaluating {config['name']} (candidate pool={CANDIDATE_POOL}, top_k={FINAL_TOP_K}) ===")
        results[config["name"]] = run_one_config(config, dataset, corpus_dir, scratch_root)
        print(json.dumps(results[config["name"]], indent=2))

    report_dir = Path("evaluation/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"reranking_comparison_{timestamp}.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n\n| Config             | Recall@5 | MRR   | nDCG@5 | Retrieval p50 | Rerank p50 | Total p50 |")
    print("|--------------------|---------:|------:|-------:|--------------:|-----------:|----------:|")
    for config in CONFIGS:
        m = results[config["name"]]
        print(
            f"| {config['name']:<18} | {m.get('recall@5', 0):.3f}    | {m.get('mrr', 0):.3f} "
            f"| {m.get('ndcg@5', 0):.3f}  | {m['retrieval_latency_p50_ms']:>13.2f} "
            f"| {m['rerank_latency_p50_ms']:>10.2f} | {m['total_latency_p50_ms']:>9.2f} |"
        )
    print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
