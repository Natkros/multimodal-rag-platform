from __future__ import annotations

import json
from unittest.mock import patch

from app.services.evaluation.experiment_log import experiment_metadata, write_experiment_report


def test_experiment_metadata_includes_core_fields():
    metadata = experiment_metadata()
    assert "generated_at" in metadata
    assert "python_version" in metadata
    assert "git_commit" in metadata
    assert "git_dirty" in metadata


def test_experiment_metadata_git_commit_is_real_when_in_a_repo():
    """This project's own working tree is a real git repo, so this should return
    an actual commit hash, not a placeholder - proves the subprocess call works,
    not just that the function returns some dict shape."""
    metadata = experiment_metadata()
    assert metadata["git_commit"] is not None
    assert len(metadata["git_commit"]) == 40  # full SHA-1 hex digest


def test_experiment_metadata_handles_git_not_available():
    with patch("subprocess.run", side_effect=FileNotFoundError("no git")):
        metadata = experiment_metadata()
    assert metadata["git_commit"] is None
    assert metadata["git_dirty"] is None


def test_write_experiment_report_wraps_report_with_metadata(tmp_path):
    report_path = write_experiment_report({"metrics": {"recall@5": 0.9}}, "test_experiment", report_dir=tmp_path)

    assert report_path.exists()
    assert report_path.parent == tmp_path
    assert report_path.name.startswith("test_experiment_")

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["metrics"]["recall@5"] == 0.9
    assert "experiment" in data
    assert "generated_at" in data["experiment"]


def test_write_experiment_report_creates_report_dir_if_missing(tmp_path):
    nested_dir = tmp_path / "nested" / "reports"
    write_experiment_report({"foo": "bar"}, "test", report_dir=nested_dir)
    assert nested_dir.is_dir()
    assert len(list(nested_dir.glob("test_*.json"))) == 1
