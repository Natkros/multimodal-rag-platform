#!/usr/bin/env python
"""Phase 25 load test: starts a real `uvicorn` process (not TestClient — a real
ASGI server accepting real concurrent TCP connections) against an isolated
SQLite/local-vector-store backend, fires concurrent requests at it with a thread
pool, and reports real throughput/latency numbers. See
docs/decisions/0025-phase25-load-testing.md for what this does and doesn't cover —
most importantly, POST /query is excluded (get_llm_client() raises
LLMNotConfiguredError, mapped to 503, on every call with no ANTHROPIC_API_KEY
configured, regardless of retrieval outcome), and this runs against SQLite/dev
hardware, not the Postgres + cloud setup docs/deployment.md's render.yaml targets.

Usage:
    python scripts/load_test.py --concurrency 20 --requests-per-worker 20
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8321"


def _wait_for_server(timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{BASE_URL}/health", timeout=1.0)
            if resp.status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(0.3)
    raise RuntimeError("Server did not become healthy in time")


def _seed_documents(n: int = 5) -> list[str]:
    document_ids = []
    for i in range(n):
        content = f"Acme Corporation fact sheet number {i}. Revenue grew steadily. " * 30
        resp = httpx.post(
            f"{BASE_URL}/documents/upload",
            files={"file": (f"loadtest_seed_{i}.txt", content.encode(), "text/plain")},
            timeout=30.0,
        )
        resp.raise_for_status()
        document_ids.append(resp.json()["document_id"])
    return document_ids


REQUEST_TIMEOUT_S = 10.0


def _one_request(client: httpx.Client, endpoint: str, method: str = "GET", **kwargs) -> dict:
    start = time.perf_counter()
    try:
        resp = client.request(
            method, endpoint, timeout=httpx.Timeout(REQUEST_TIMEOUT_S), **kwargs
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return {"status_code": resp.status_code, "latency_ms": latency_ms, "error": None}
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return {"status_code": None, "latency_ms": latency_ms, "error": f"{type(exc).__name__}: {exc}"}


def _worker(worker_id: int, requests_per_worker: int, document_ids: list[str]) -> list[dict]:
    results = []
    with httpx.Client(base_url=BASE_URL) as client:
        for i in range(requests_per_worker):
            doc_id = document_ids[i % len(document_ids)]
            endpoint_choice = i % 3
            if endpoint_choice == 0:
                results.append(_one_request(client, "/health"))
            elif endpoint_choice == 1:
                results.append(_one_request(client, "/documents"))
            else:
                results.append(_one_request(client, f"/documents/{doc_id}/chunks"))
    return results


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * p
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--requests-per-worker", type=int, default=20)
    args = parser.parse_args()

    tmp_dir = Path(tempfile.mkdtemp(prefix="loadtest_"))
    env = {
        "DATABASE_URL": f"sqlite:///{tmp_dir}/loadtest.db",
        "DATA_DIR": str(tmp_dir),
        "UPLOAD_DIR": str(tmp_dir / "uploads"),
        "LOCAL_VECTOR_STORE_DIR": str(tmp_dir / "vector_store"),
        "LOCAL_SPARSE_INDEX_DIR": str(tmp_dir / "sparse_index"),
        "VECTOR_STORE": "local",
        "EMBEDDING_PROVIDER": "local",
        "ENVIRONMENT": "test",
        "CACHE_ENABLED": "false",
        "RATE_LIMIT_ENABLED": "false",
        "API_KEY": "",
    }
    import os

    full_env = {**os.environ, **env}

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8321"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server()
        print("Server healthy. Seeding documents...")
        document_ids = _seed_documents(5)
        print(f"Seeded {len(document_ids)} documents. Starting load test: "
              f"{args.concurrency} workers x {args.requests_per_worker} requests each "
              f"({args.concurrency * args.requests_per_worker} total requests)")

        # Hard deadline: each worker does requests_per_worker sequential requests,
        # each capped at REQUEST_TIMEOUT_S, so a healthy run finishes well within
        # requests_per_worker * REQUEST_TIMEOUT_S regardless of concurrency. A
        # generous multiple on top of that bounds the whole phase so a pathological
        # hang (this script's first run took ~4.85 REAL HOURS before a single
        # per-request timeout ever fired - see docs/decisions/0025-phase25-load-testing.md)
        # can't do that again.
        hard_deadline_s = args.requests_per_worker * REQUEST_TIMEOUT_S * 3 + 30
        start = time.perf_counter()
        all_results: list[dict] = []
        executor = ThreadPoolExecutor(max_workers=args.concurrency)
        try:
            futures = [
                executor.submit(_worker, i, args.requests_per_worker, document_ids)
                for i in range(args.concurrency)
            ]
            done, not_done = wait(futures, timeout=hard_deadline_s)
            for future in done:
                all_results.extend(future.result())
            if not_done:
                print(
                    f"\nWARNING: hard deadline of {hard_deadline_s}s hit with "
                    f"{len(not_done)}/{len(futures)} workers still running - aborting "
                    "rather than waiting indefinitely. Results below only reflect "
                    "workers that finished in time."
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        wall_time_s = time.perf_counter() - start

        latencies = [r["latency_ms"] for r in all_results]
        errors = [r for r in all_results if r["error"] is not None or (r["status_code"] or 0) >= 400]

        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "config": {"concurrency": args.concurrency, "requests_per_worker": args.requests_per_worker},
            "total_requests": len(all_results),
            "wall_time_s": round(wall_time_s, 3),
            "throughput_req_per_s": round(len(all_results) / wall_time_s, 2),
            "error_count": len(errors),
            "error_rate": round(len(errors) / len(all_results), 4) if all_results else None,
            "latency_ms": {
                "min": round(min(latencies), 2) if latencies else None,
                "p50": round(_percentile(latencies, 0.50), 2),
                "p95": round(_percentile(latencies, 0.95), 2),
                "p99": round(_percentile(latencies, 0.99), 2),
                "max": round(max(latencies), 2) if latencies else None,
                "mean": round(statistics.mean(latencies), 2) if latencies else None,
            },
            "note": (
                "POST /query excluded - no ANTHROPIC_API_KEY configured, every call "
                "would 503 regardless of retrieval outcome. Endpoints tested: "
                "GET /health, GET /documents, GET /documents/{id}/chunks. Run against "
                "SQLite + LocalVectorStore on this dev machine's hardware, single "
                "uvicorn process/worker - not representative of the Postgres + cloud "
                "setup in render.yaml. See docs/decisions/0025-phase25-load-testing.md."
            ),
        }
        print(json.dumps(report, indent=2))

        out_dir = Path("evaluation/reports")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"load_test_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
        out_path.write_text(json.dumps(report, indent=2))
        print(f"\nReport written to {out_path}")

        if errors:
            print(f"\n{len(errors)} errors/failures out of {len(all_results)} requests:")
            for e in errors[:5]:
                print(f"  status={e['status_code']} error={e['error']}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
