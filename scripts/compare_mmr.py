#!/usr/bin/env python
"""Phase 26 experiment: measure dense retrieval with vs. without MMR
diversification. Per this project's rule ("do not assume X improves the system;
prove it experimentally" — the same discipline Phase 7 applied to reranking),
this produces a real before/after number on both relevance (recall/MRR/nDCG,
unaffected chunk_ids so the exact metrics as Phase 6/7) and a new diversity
metric (average pairwise cosine similarity among the final selected chunks —
lower means less redundant content in the result set).

Holds RETRIEVAL_MODE=dense fixed (Phase 1's baseline) and only varies
MMR_ENABLED, so any delta is attributable to MMR alone.

Usage:
    python scripts/compare_mmr.py
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
    {"name": "dense_no_mmr", "mmr_enabled": "false"},
    {"name": "dense_with_mmr", "mmr_enabled": "true"},
]
CANDIDATE_POOL = 30
FINAL_TOP_K = 5
MMR_LAMBDA = 0.5


def _reset_for_config(name: str, mmr_enabled: str, scratch_root: Path):
    config_dir = scratch_root / name
    if config_dir.exists():
        shutil.rmtree(config_dir)
    config_dir.mkdir(parents=True)

    os.environ["DATABASE_URL"] = f"sqlite:///{config_dir / 'mmr_experiment.db'}"
    os.environ["DATA_DIR"] = str(config_dir)
    os.environ["UPLOAD_DIR"] = str(config_dir / "uploads")
    os.environ["LOCAL_VECTOR_STORE_DIR"] = str(config_dir / "vector_store")
    os.environ["LOCAL_SPARSE_INDEX_DIR"] = str(config_dir / "sparse_index")
    os.environ["VECTOR_STORE"] = "local"
    os.environ["EMBEDDING_PROVIDER"] = "local"
    os.environ["CHUNKING_STRATEGY"] = "recursive"
    os.environ["RETRIEVAL_MODE"] = "dense"  # Phase 1's baseline, held fixed
    os.environ["MMR_ENABLED"] = mmr_enabled
    os.environ["MMR_LAMBDA"] = str(MMR_LAMBDA)

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


def run_one_config(config: dict, dataset: list[dict], corpus_dir: Path, scratch_root: Path) -> dict:
    settings = _reset_for_config(config["name"], config["mmr_enabled"], scratch_root)

    import run_eval

    from app.services.embeddings.factory import get_embedder
    from app.services.evaluation.retrieval_metrics import aggregate_metrics
    from app.services.retrieval.factory import get_retriever, get_vector_store
    from app.services.retrieval.mmr import average_pairwise_similarity, select_with_mmr

    run_eval.ingest_corpus(corpus_dir)

    embedder = get_embedder(settings)
    vector_store = get_vector_store(settings, embedder.dimension)
    retriever = get_retriever(settings, embedder, vector_store)

    per_query_retrieved: list[list[str]] = []
    per_query_relevant: list[set[str]] = []
    latencies_ms: list[float] = []
    diversities: list[float] = []

    for case in dataset:
        pool_k = CANDIDATE_POOL if settings.mmr_enabled else FINAL_TOP_K
        start = time.perf_counter()
        candidates = retriever.retrieve(case["question"], top_k=pool_k)
        if settings.mmr_enabled:
            candidate_vectors = embedder.embed_documents([c.text for c in candidates])
            final = select_with_mmr(candidates, candidate_vectors, FINAL_TOP_K, MMR_LAMBDA)
            final_vectors = embedder.embed_documents([c.text for c in final])
        else:
            final = candidates[:FINAL_TOP_K]
            final_vectors = embedder.embed_documents([c.text for c in final])
        latencies_ms.append((time.perf_counter() - start) * 1000)
        diversities.append(average_pairwise_similarity(final_vectors))

        per_query_retrieved.append([c.chunk_id for c in final])
        per_query_relevant.append(set(case.get("expected_chunks", [])))

    metrics = aggregate_metrics(per_query_retrieved, per_query_relevant)
    metrics["latency_p50_ms"] = round(sorted(latencies_ms)[len(latencies_ms) // 2] if latencies_ms else 0, 3)
    metrics["avg_intra_result_similarity"] = round(sum(diversities) / len(diversities), 4) if diversities else 0.0
    return metrics


def main() -> None:
    import run_eval

    dataset_path = Path("evaluation/datasets/qa_dataset.jsonl")
    corpus_dir = Path("sample_docs")
    scratch_root = Path("data/mmr_experiments")

    dataset = run_eval.load_dataset(dataset_path)
    results = {}
    for config in CONFIGS:
        print(f"\n=== Evaluating {config['name']} (candidate pool={CANDIDATE_POOL}, top_k={FINAL_TOP_K}) ===")
        results[config["name"]] = run_one_config(config, dataset, corpus_dir, scratch_root)
        print(json.dumps(results[config["name"]], indent=2))

    report_dir = Path("evaluation/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"mmr_comparison_{timestamp}.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n\n| Config          | Recall@5 | MRR   | nDCG@5 | Avg intra-result similarity | Latency p50 |")
    print("|-----------------|---------:|------:|-------:|-----------------------------:|------------:|")
    for config in CONFIGS:
        m = results[config["name"]]
        print(
            f"| {config['name']:<15} | {m.get('recall@5', 0):.3f}    | {m.get('mrr', 0):.3f} "
            f"| {m.get('ndcg@5', 0):.3f}  | {m['avg_intra_result_similarity']:>28.4f} "
            f"| {m['latency_p50_ms']:>11.2f} |"
        )
    print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
