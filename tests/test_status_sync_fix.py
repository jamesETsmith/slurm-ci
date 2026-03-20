"""Test to verify that status watcher correctly detects job completion."""

import tempfile
from pathlib import Path

import toml

from slurm_ci.database import Job, SessionLocal
from slurm_ci.status_watcher import StatusWatcher


def test_status_update_on_completion():
    """Test status updates from running to completed."""

    # Create a temporary directory for status files
    with tempfile.TemporaryDirectory() as tmpdir:
        status_dir = Path(tmpdir)

        # Create initial status file (job running)
        status_file = status_dir / "test_job.toml"
        initial_data = {
            "project": {
                "name": "test_project",
                "workflow_file": "/path/to/workflow.yml",
                "working_directory": "/path/to/project",
            },
            "git": {
                "commit": "abc123def456",  # pragma: allowlist secret
                "branch": "main",
            },
            "ci": {
                "slurm-ci_version": "0.1.0",
                "logfile_path": "/path/to/log.txt",
            },
            "matrix": {
                "python": "3.9",
            },
            "runtime": {
                "start_time": 1234567890.0,
            },
        }

        with open(status_file, "w") as f:
            toml.dump(initial_data, f)

        # Sync to database
        watcher = StatusWatcher(str(status_dir))
        watcher.sync_file_to_db(status_file)

        # Verify job is in "running" state
        db = SessionLocal()
        job = db.query(Job).filter(Job.name == "python:3.9").first()
        assert job is not None, "Job should exist in database"
        assert job.status == "running", f"Job should be 'running', got '{job.status}'"
        assert job.exit_code is None, "Exit code should be None for running job"
        assert job.end_time is None, "End time should be None for running job"
        db.close()

        # Simulate job completion by adding runtime.end section
        completed_data = initial_data.copy()
        completed_data["runtime"]["end"] = {
            "time": 1234567990,
            "exit_code": 0,
        }

        with open(status_file, "w") as f:
            toml.dump(completed_data, f)

        # Sync again
        watcher.sync_file_to_db(status_file)

        # Verify job status updated to "completed"
        db = SessionLocal()
        job = db.query(Job).filter(Job.name == "python:3.9").first()
        assert job is not None, "Job should still exist in database"
        assert job.status == "completed", (
            f"Job should be 'completed', got '{job.status}'"
        )
        assert job.exit_code == 0, f"Exit code should be 0, got {job.exit_code}"
        assert job.end_time is not None, "End time should be set"
        db.close()

        print("✓ Test passed: Status watcher correctly detects job completion")


if __name__ == "__main__":
    test_status_update_on_completion()
