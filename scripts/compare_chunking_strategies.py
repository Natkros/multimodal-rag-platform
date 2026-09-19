#!/usr/bin/env python
"""Phase 3 experiment: measure fixed-size vs. recursive vs. semantic chunking.

Each strategy gets its own isolated SQLite DB and local vector store — driven through
environment variables and cache resets, the same pattern tests/conftest.py's
`test_settings` fixture uses — so results can't leak between runs. Each strategy then
ingests the full sample_docs corpus and is evaluated against every question in the
dataset using content-based relevance (app/services/evaluation/content_metrics.py):
chunk_ids aren't comparable across strategies since each one splits documents at
different boundaries, so "did a retrieved chunk contain the expected answer text"
is the strategy-agnostic ground truth here, not an exact chunk_id match.

Usage:
    python scripts/compare_chunking_strategies.py
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

STRATEGIES = ["fixed", "recursive", "semantic"]


def _reset_for_strategy(strategy: str, scratch_root: Path):
    """Points every env-driven setting at a fresh, strategy-specific directory and
    clears every process-wide cache that would otherwise leak state (settings,
    embedder, local vector store, DB engine/session) between strategy runs."""
    strategy_dir = scratch_root / strategy
    if strategy_dir.exists():
        shutil.rmtree(strategy_dir)
    strategy_dir.mkdir(parents=True)

    os.environ["DATABASE_URL"] = f"sqlite:///{strategy_dir / 'chunking_experiment.db'}"
    os.environ["DATA_DIR"] = str(strategy_dir)
    os.environ["UPLOAD_DIR"] = str(strategy_dir / "uploads")
    os.environ["LOCAL_VECTOR_STORE_DIR"] = str(strategy_dir / "vector_store")
    os.environ["VECTOR_STORE"] = "local"
    os.environ["EMBEDDING_PROVIDER"] = "local"
    os.environ["CHUNKING_STRATEGY"] = strategy

    import app.models.db as db_module
    from app.core.config import get_settings
    from app.services.embeddings.local_embedder import get_local_embedder
    from app.services.retrieval.factory import _cached_local_store

    get_settings.cache_clear()
    get_local_embedder.cache_clear()
    _cached_local_store.cache_clear()
    db_module._engine = None
    db_module._SessionLocal = None

    return get_settings()


def run_one_strategy(strategy: str, dataset: list[dict], corpus_dir: Path, scratch_root: Path, top_k: int) -> dict:
    settings = _reset_for_strategy(strategy, scratch_root)

    import run_eval

    from app.services.embeddings.factory import get_embedder
    from app.services.evaluation.content_metrics import aggregate_content_metrics
    from app.services.retrieval.factory import get_vector_store
    from app.services.retrieval.retriever import DenseRetriever

    run_eval.ingest_corpus(corpus_dir)

    embedder = get_embedder(settings)
    vector_store = get_vector_store(settings, embedder.dimension)
    retriever = DenseRetriever(embedder=embedder, vector_store=vector_store)

    per_query_texts: list[list[str]] = []
    per_query_substrings: list[list[str]] = []
    latencies_ms: list[float] = []

    for case in dataset:
        start = time.perf_counter()
        results = retriever.retrieve(case["question"], top_k=top_k)
        latencies_ms.append((time.perf_counter() - start) * 1000)
        per_query_texts.append([r.text for r in results])
        per_query_substrings.append(case.get("expected_answer_substrings", []))

    metrics = aggregate_content_metrics(per_query_texts, per_query_substrings)
    metrics["retrieval_latency_p50_ms"] = round(
        sorted(latencies_ms)[len(latencies_ms) // 2] if latencies_ms else 0, 3
    )
    metrics["retrieval_latency_p95_ms"] = round(
        sorted(latencies_ms)[int(len(latencies_ms) * 0.95)] if latencies_ms else 0, 3
    )
    return metrics


def main() -> None:
    import run_eval

    dataset_path = Path("evaluation/datasets/qa_dataset.jsonl")
    corpus_dir = Path("sample_docs")
    scratch_root = Path("data/chunking_experiments")
    top_k = 5

    dataset = run_eval.load_dataset(dataset_path)
    results = {}
    for strategy in STRATEGIES:
        print(f"\n=== Ingesting + evaluating strategy: {strategy} ===")
        start = time.perf_counter()
        results[strategy] = run_one_strategy(strategy, dataset, corpus_dir, scratch_root, top_k)
        results[strategy]["total_wall_time_s"] = round(time.perf_counter() - start, 2)
        print(json.dumps(results[strategy], indent=2))

    report_dir = Path("evaluation/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"chunking_strategy_comparison_{timestamp}.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(
        "\n\n| Strategy  | HitRate@5 | Precision@5 | nDCG@5 | MRR   | "
        "Latency p50 (ms) | Ingest+Eval wall time (s) |"
    )
    print(
        "|-----------|----------:|-------------:|-------:|------:|"
        "-----------------:|--------------------------:|"
    )
    for strategy in STRATEGIES:
        m = results[strategy]
        print(
            f"| {strategy:<9} | {m.get('hit_rate@5', 0):.3f}     | {m.get('precision@5', 0):.3f}        "
            f"| {m.get('ndcg@5', 0):.3f}  | {m.get('mrr', 0):.3f} | {m.get('retrieval_latency_p50_ms', 0):>16.2f} "
            f"| {m.get('total_wall_time_s', 0):>26.2f} |"
        )
    print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
