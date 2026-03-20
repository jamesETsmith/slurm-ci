"""Focused tests for status_watcher.py."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from slurm_ci.status_watcher import StatusWatcher


def test_scan_status_files_missing_directory(tmp_path: Path) -> None:
    watcher = StatusWatcher(str(tmp_path / "does-not-exist"))
    assert watcher.scan_status_files() == []


def test_read_status_file_invalid_toml(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.toml"
    bad_file.write_text("not = [valid")
    watcher = StatusWatcher(str(tmp_path))
    assert watcher.read_status_file(bad_file) is None


def test_extract_build_info_defaults() -> None:
    watcher = StatusWatcher()
    info = watcher.extract_build_info({})
    assert info["repo_full_name"] == "unknown"
    assert info["commit_sha"] == "unknown"
    assert info["build_key"] == "unknown#unknown#"


def test_extract_job_info_uses_runtime_without_sacct(tmp_path: Path) -> None:
    watcher = StatusWatcher(str(tmp_path))
    status_file = tmp_path / "status.toml"
    status_file.write_text("")
    status_data = {
        "matrix": {"os": "ubuntu", "py": "3.12"},
        "runtime": {"start_time": 100.0, "end": {"time": 200.0, "exit_code": 0}},
        "ci": {"logfile_path": "/tmp/test.log"},
        "slurm": {},
    }
    info = watcher.extract_job_info(status_data, status_file)
    assert info["name"] == "os:ubuntu_py:3.12"
    assert info["status"] == "completed"
    assert info["exit_code"] == 0
    assert info["matrix_args"] == json.dumps({"os": "ubuntu", "py": "3.12"})


def test_extract_job_info_prefers_sacct_for_state_and_exit(tmp_path: Path) -> None:
    watcher = StatusWatcher(str(tmp_path))
    status_file = tmp_path / "job.toml"
    status_file.write_text(
        "[runtime]\nstart_time = 100\n[runtime.end]\ntime = 200\nexit_code = 0\n"
    )
    status_data = {
        "matrix": {},
        "runtime": {"start_time": 100.0, "end": {"time": 200.0, "exit_code": 0}},
        "ci": {},
        "slurm": {"job_id": 1234},
    }
    with patch("slurm_ci.status_watcher.get_job_info_from_sacct") as mock_sacct:
        mock_sacct.return_value = {"state": "FAILED", "exit_code": 7}
        info = watcher.extract_job_info(status_data, status_file)
    assert info["status"] == "failed"
    assert info["exit_code"] == 7


def test_update_build_status_transitions() -> None:
    watcher = StatusWatcher()
    build = Mock()
    session = Mock()
    query = session.query.return_value
    filtered = query.filter.return_value

    filtered.all.return_value = []
    watcher.update_build_status(session, build)
    assert build.status == "pending"

    filtered.all.return_value = [Mock(status="completed"), Mock(status="completed")]
    watcher.update_build_status(session, build)
    assert build.status == "completed"

    filtered.all.return_value = [Mock(status="completed"), Mock(status="failed")]
    watcher.update_build_status(session, build)
    assert build.status == "failed"

    filtered.all.return_value = [Mock(status="running"), Mock(status="completed")]
    watcher.update_build_status(session, build)
    assert build.status == "running"
