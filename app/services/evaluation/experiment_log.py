"""Phase 29: experiment tracking metadata, shared by every report-writing script
(scripts/run_eval.py, compare_*.py, profile_pipeline.py, load_test.py) so a
measured number can always be traced back to the exact code that produced it —
the git commit, whether the working tree was clean, when, and with what Python
version. No MLflow/W&B dependency: this project has no experiment volume or team
of collaborators that would justify a hosted tracking service, and a JSON file per
run in `evaluation/reports/` (already this project's convention since Phase 1)
plus this metadata is the whole problem "which commit produced this number"
actually needs solved. See docs/decisions/0029-phase29-experiment-tracking.md.
"""
from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def _git_info() -> dict:
    def _run(args: list[str]) -> str | None:
        try:
            return subprocess.run(
                args, capture_output=True, text=True, check=True, timeout=5
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None

    commit = _run(["git", "rev-parse", "HEAD"])
    if commit is None:
        return {"git_commit": None, "git_dirty": None}
    status = _run(["git", "status", "--porcelain"])
    return {"git_commit": commit, "git_dirty": bool(status) if status is not None else None}


def experiment_metadata() -> dict:
    """Call once per report, at the point a script is about to write its results —
    not cached, since a long-running script could be re-run against a different
    commit than when this module was first imported."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
        **_git_info(),
    }


def write_experiment_report(report: dict, name_prefix: str, report_dir: Path | None = None) -> Path:
    """Wraps `report` with experiment_metadata() under an `"experiment"` key and
    writes it to `evaluation/reports/{name_prefix}_{timestamp}.json` — the same
    naming convention every report-writing script already used before this phase,
    so existing tooling (Phase 28's dashboard, scripts/list_experiments.py) that
    globs `evaluation/reports/*.json` doesn't need to change to find these."""
    report_dir = report_dir or Path("evaluation/reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    full_report = {"experiment": experiment_metadata(), **report}

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_path = report_dir / f"{name_prefix}_{timestamp}.json"
    out_path.write_text(json.dumps(full_report, indent=2), encoding="utf-8")
    return out_path
