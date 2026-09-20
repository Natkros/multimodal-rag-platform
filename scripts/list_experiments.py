#!/usr/bin/env python
"""Phase 29: lists every experiment report in evaluation/reports/, showing which
git commit produced each one (for reports written after this phase — see
docs/decisions/0029-phase29-experiment-tracking.md for why older reports don't
have this and aren't retroactively rewritten to pretend they did).

Usage:
    python scripts/list_experiments.py
    python scripts/list_experiments.py --name-filter mmr
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _headline_metric(data: dict) -> str:
    metrics_blob = data.get("metrics", data)
    for key in ("recall@5", "throughput_req_per_s", "avg_intra_result_similarity"):
        if isinstance(metrics_blob, dict) and key in metrics_blob:
            return f"{key}={metrics_blob[key]}"
    return "-"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=Path("evaluation/reports"))
    parser.add_argument("--name-filter", type=str, default=None)
    args = parser.parse_args()

    if not args.report_dir.is_dir():
        print(f"No such directory: {args.report_dir}")
        return

    rows = []
    for path in sorted(args.report_dir.glob("*.json")):
        if args.name_filter and args.name_filter not in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            rows.append((path.name, "?", "?", f"unreadable: {exc}"))
            continue
        experiment = data.get("experiment") if isinstance(data, dict) else None
        if experiment:
            commit = (experiment.get("git_commit") or "unknown")[:8]
            dirty = " (dirty)" if experiment.get("git_dirty") else ""
            commit_str = f"{commit}{dirty}"
        else:
            commit_str = "pre-Phase-29 (no metadata)"
        rows.append((path.name, commit_str, _headline_metric(data), ""))

    if not rows:
        print("No experiment reports found.")
        return

    name_width = max(len(r[0]) for r in rows)
    commit_width = max(len(r[1]) for r in rows)
    for name, commit_str, headline, note in rows:
        print(f"{name:<{name_width}}  {commit_str:<{commit_width}}  {headline}{('  ' + note) if note else ''}")


if __name__ == "__main__":
    main()
