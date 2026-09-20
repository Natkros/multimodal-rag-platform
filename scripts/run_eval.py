#!/usr/bin/env python
"""Evaluation harness CLI (Phase 1 baseline / Phase 13 groundwork).

Ingests the corpus referenced by the dataset, runs dense-only retrieval for every
question, computes deterministic retrieval metrics, and writes a timestamped report.

Usage:
    python scripts/run_eval.py \
        --dataset evaluation/datasets/qa_dataset.jsonl \
        --corpus sample_docs \
        --top-k 5

This is the "baseline" referenced throughout docs/evaluation.md — later phases
(hybrid search, reranking) are compared against the report this script produces.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.models.db import Document, get_session_factory, init_db
from app.repositories.document_repository import DocumentRepository
from app.services.embeddings.factory import get_embedder
from app.services.evaluation.retrieval_metrics import aggregate_metrics
from app.services.ingestion.pipeline import run_ingestion
from app.services.retrieval.factory import get_vector_store
from app.services.retrieval.retriever import DenseRetriever
from app.utils.hashing import classify_file_type, deterministic_document_id, sha256_bytes


def ingest_corpus(corpus_dir: Path) -> None:
    init_db()
    session_factory = get_session_factory()
    settings = get_settings()
    db = session_factory()
    repo = DocumentRepository(db)

    for path in sorted(corpus_dir.iterdir()):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        file_type = classify_file_type(path.name)
        if file_type not in settings.allowed_file_types:
            print(f"skip (unsupported type): {path.name}")
            continue
        file_hash = sha256_bytes(raw)
        document_id = deterministic_document_id(file_hash)

        existing = repo.get(document_id)
        if existing is not None and existing.processing_status == "INDEXED":
            print(f"already indexed: {path.name}")
            continue
        if existing is None:
            repo.create(
                Document(
                    document_id=document_id,
                    filename=path.name,
                    file_type=file_type,
                    file_hash=file_hash,
                    processing_status="UPLOADED",
                )
            )
        print(f"ingesting: {path.name} ({file_type})")
        run_ingestion(document_id, file_type, raw, path.name, settings)
    db.close()


def load_dataset(path: Path) -> list[dict]:
    cases = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def run(dataset_path: Path, corpus_dir: Path, top_k: int, report_dir: Path) -> dict:
    ingest_corpus(corpus_dir)

    settings = get_settings()
    embedder = get_embedder(settings)
    vector_store = get_vector_store(settings, embedder.dimension)
    retriever = DenseRetriever(embedder=embedder, vector_store=vector_store)

    cases = load_dataset(dataset_path)
    per_query_retrieved: list[list[str]] = []
    per_query_relevant: list[set[str]] = []
    latencies_ms: list[float] = []
    rows = []

    for case in cases:
        start = time.perf_counter()
        results = retriever.retrieve(case["question"], top_k=top_k)
        latency_ms = (time.perf_counter() - start) * 1000
        latencies_ms.append(latency_ms)

        retrieved_ids = [r.chunk_id for r in results]
        relevant_ids = set(case.get("expected_chunks", []))
        per_query_retrieved.append(retrieved_ids)
        per_query_relevant.append(relevant_ids)
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "query_type": case.get("query_type"),
                "retrieved": retrieved_ids,
                "expected": list(relevant_ids),
                "latency_ms": round(latency_ms, 2),
            }
        )

    metrics = aggregate_metrics(per_query_retrieved, per_query_relevant)
    metrics["latency_p50_ms"] = sorted(latencies_ms)[len(latencies_ms) // 2] if latencies_ms else 0
    metrics["latency_p95_ms"] = (
        sorted(latencies_ms)[int(len(latencies_ms) * 0.95)] if latencies_ms else 0
    )

    from app.services.evaluation.experiment_log import write_experiment_report

    report_path = write_experiment_report(
        {"system": "dense_only", "metrics": metrics, "rows": rows},
        name_prefix="dense_baseline",
        report_dir=report_dir,
    )
    print(json.dumps(metrics, indent=2))
    print(f"\nReport written to {report_path}")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/datasets/qa_dataset.jsonl"))
    parser.add_argument("--corpus", type=Path, default=Path("sample_docs"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--report-dir", type=Path, default=Path("evaluation/reports"))
    args = parser.parse_args()
    run(args.dataset, args.corpus, args.top_k, args.report_dir)
