"""Focused tests for status_watcher.py."""

import json
import random
from pathlib import Path
from unittest.mock import Mock, patch

import toml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from slurm_ci.database import Base, Job
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

    filtered.all.return_value = [
        Mock(status="completed"),
        Mock(status="incomplete"),
    ]
    watcher.update_build_status(session, build)
    assert build.status == "incomplete"

    filtered.all.return_value = [
        Mock(status="failed"),
        Mock(status="incomplete"),
    ]
    watcher.update_build_status(session, build)
    assert build.status == "failed"


def test_reap_incomplete_jobs_marks_stale_jobs(tmp_path: Path) -> None:
    """Jobs whose Slurm ID is no longer active get marked incomplete."""
    engine = create_engine(f"sqlite:///{tmp_path / 'reap.db'}")
    Base.metadata.create_all(bind=engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    status_file = tmp_path / "running_job.toml"
    toml_data = {
        "project": {"name": "proj", "workflow_file": "ci.yml"},
        "git": {"commit": "aaa", "branch": "main"},
        "ci": {},
        "matrix": {"py": "3.12"},
        "runtime": {"start_time": 1000.0},
        "slurm": {"job_id": 999},
    }
    with open(status_file, "w") as f:
        toml.dump(toml_data, f)

    session = test_session_local()
    from slurm_ci.database import Build as BuildModel
    from slurm_ci.database import Job as JobModel

    build = BuildModel(
        repo_full_name="proj",
        commit_sha="aaa",
        branch="main",
        workflow_file="ci.yml",
        status="running",
    )
    session.add(build)
    session.commit()

    job = JobModel(
        build_id=build.id,
        name="py:3.12",
        status="running",
        status_file_path=str(status_file),
    )
    session.add(job)
    session.commit()
    session.close()

    watcher = StatusWatcher(str(tmp_path))

    with (
        patch("slurm_ci.status_watcher.SessionLocal", test_session_local),
        patch("slurm_ci.status_watcher.is_slurm_job_active", return_value=False),
    ):
        reaped = watcher.reap_incomplete_jobs()

    assert reaped == 1

    session = test_session_local()
    job = session.query(JobModel).first()
    assert job.status == "incomplete"
    build = session.query(BuildModel).first()
    assert build.status == "incomplete"
    session.close()


def test_reap_skips_jobs_still_active(tmp_path: Path) -> None:
    """Jobs whose Slurm ID is still active should not be reaped."""
    engine = create_engine(f"sqlite:///{tmp_path / 'reap_active.db'}")
    Base.metadata.create_all(bind=engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    status_file = tmp_path / "active_job.toml"
    toml_data = {
        "project": {"name": "proj", "workflow_file": "ci.yml"},
        "git": {"commit": "bbb", "branch": "main"},
        "ci": {},
        "matrix": {},
        "runtime": {"start_time": 1000.0},
        "slurm": {"job_id": 888},
    }
    with open(status_file, "w") as f:
        toml.dump(toml_data, f)

    session = test_session_local()
    from slurm_ci.database import Build as BuildModel
    from slurm_ci.database import Job as JobModel

    build = BuildModel(
        repo_full_name="proj",
        commit_sha="bbb",
        branch="main",
        workflow_file="ci.yml",
        status="running",
    )
    session.add(build)
    session.commit()
    job = JobModel(
        build_id=build.id,
        name="default",
        status="running",
        status_file_path=str(status_file),
    )
    session.add(job)
    session.commit()
    session.close()

    watcher = StatusWatcher(str(tmp_path))

    with (
        patch("slurm_ci.status_watcher.SessionLocal", test_session_local),
        patch("slurm_ci.status_watcher.is_slurm_job_active", return_value=True),
    ):
        reaped = watcher.reap_incomplete_jobs()

    assert reaped == 0

    session = test_session_local()
    job = session.query(JobModel).first()
    assert job.status == "running"
    session.close()


def test_extract_job_info_fuzz_runtime_terminal_not_overwritten(tmp_path: Path) -> None:
    """Fuzz runtime/sacct combinations to avoid terminal->running regressions."""
    watcher = StatusWatcher(str(tmp_path))
    status_file = tmp_path / "fuzz_status.toml"
    status_file.write_text("")

    rng = random.Random(42)
    sacct_states = [
        None,
        "RUNNING",
        "PENDING",
        "CONFIGURING",
        "COMPLETED",
        "FAILED",
        "TIMEOUT",
        "OUT_OF_MEMORY",
        "CANCELLED",
        "WEIRD_STATE",
    ]

    for _ in range(300):
        has_start = rng.choice([True, False])
        has_end = rng.choice([True, False])

        runtime = {}
        if has_start:
            runtime["start_time"] = float(rng.randint(1, 100_000))
        if has_end:
            runtime["end"] = {
                "time": float(rng.randint(100_001, 200_000)),
                "exit_code": rng.choice([0, 1, 2, 127]),
            }

        status_data = {
            "matrix": {"seed": str(rng.randint(0, 9999))},
            "runtime": runtime,
            "ci": {},
            "slurm": {"job_id": 1234},
        }

        slurm_state = rng.choice(sacct_states)
        sacct_exit_code = rng.choice([None, 0, 1, 3, 9])
        with patch("slurm_ci.status_watcher.get_job_info_from_sacct") as mock_sacct:
            if slurm_state is None:
                mock_sacct.return_value = None
            else:
                mock_sacct.return_value = {
                    "state": slurm_state,
                    "exit_code": sacct_exit_code,
                }
            info = watcher.extract_job_info(status_data, status_file)

        # If runtime has an explicit end marker, we should never classify it
        # as pending/running due to lagging scheduler state.
        if has_end:
            assert info["status"] in {"completed", "failed"}
        elif "start_time" in runtime:
            assert info["status"] in {"running", "completed", "failed", "pending"}
        else:
            assert info["status"] in {"pending", "completed", "failed", "running"}


def test_sync_file_to_db_fuzz_status_transitions_no_stale_running(
    tmp_path: Path,
) -> None:
    """Fuzz repeated status file updates and ensure DB tracks terminal failures."""
    engine = create_engine(f"sqlite:///{tmp_path / 'status_fuzz.db'}")
    Base.metadata.create_all(bind=engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    watcher = StatusWatcher(str(tmp_path))
    status_file = tmp_path / "job.toml"
    rng = random.Random(1337)

    data = {
        "project": {
            "name": "fuzz-project",
            "workflow_file": "workflows/ci.yml",
            "working_directory": str(tmp_path),
        },
        "git": {
            "commit": "abc123def",  # pragma: allowlist secret
            "branch": "main",
        },
        "ci": {
            "slurm-ci_version": "0.1.0",
            "logfile_path": str(tmp_path / "job.log"),
        },
        "matrix": {
            "python": "3.12",
        },
        "runtime": {
            "start_time": 1000.0,
        },
        "slurm": {},
    }

    with patch("slurm_ci.status_watcher.SessionLocal", test_session_local):
        with patch(
            "slurm_ci.status_watcher.get_job_info_from_sacct", return_value=None
        ):
            for _ in range(120):
                if rng.choice([True, False]):
                    data["runtime"] = {"start_time": float(rng.randint(1000, 4000))}
                    expected_status = "running"
                    expected_exit = None
                else:
                    exit_code = rng.choice([0, 1, 2, 137])
                    data["runtime"] = {
                        "start_time": float(rng.randint(1000, 4000)),
                        "end": {
                            "time": float(rng.randint(4001, 8000)),
                            "exit_code": exit_code,
                        },
                    }
                    expected_status = "completed" if exit_code == 0 else "failed"
                    expected_exit = exit_code

                with open(status_file, "w") as f:
                    toml.dump(data, f)

                assert watcher.sync_file_to_db(status_file) is True

                session = test_session_local()
                try:
                    job = session.query(Job).filter(Job.name == "python:3.12").first()
                    assert job is not None
                    assert job.status == expected_status
                    assert job.exit_code == expected_exit
                finally:
                    session.close()
