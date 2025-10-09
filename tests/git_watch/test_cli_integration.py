#!/usr/bin/env python3
"""Integration tests for git-watch CLI commands."""

import os
import tempfile
import subprocess
import time
from pathlib import Path


def test_git_watch_create_config():
    """Test creating example configuration file."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = os.path.join(temp_dir, "test-config.toml")

        # Run the create-config command
        result = subprocess.run(
            [
                "python",
                "-m",
                "slurm_ci.cli",
                "git-watch",
                "create-config",
                "--output",
                config_path,
            ],
            capture_output=True,
            text=True,
        )

        # Check command succeeded
        assert result.returncode == 0

        # Check config file was created
        assert os.path.exists(config_path)

        # Check config file has expected content
        with open(config_path, "r") as f:
            content = f.read()
            assert "daemon" in content
            assert "repository" in content
            assert "slurm-ci" in content
            assert "my-project-main" in content


def test_git_watch_status_no_daemons():
    """Test status command when no daemons are running."""
    result = subprocess.run(
        ["python", "-m", "slurm_ci.cli", "git-watch", "status"],
        capture_output=True,
        text=True,
    )

    # Command should succeed
    assert result.returncode == 0

    # Should indicate no daemons running
    assert "No git-watch daemons are currently running" in result.stdout


def test_git_watch_stop_nonexistent_daemon():
    """Test stopping a daemon that doesn't exist."""
    result = subprocess.run(
        ["python", "-m", "slurm_ci.cli", "git-watch", "stop", "nonexistent-daemon"],
        capture_output=True,
        text=True,
    )

    # Command should fail gracefully
    assert result.returncode == 0  # DaemonManager handles this gracefully
    assert "No PID file found" in result.stdout or "not running" in result.stdout


def test_git_watch_stop_all_no_daemons():
    """Test stop-all command when no daemons are running."""
    result = subprocess.run(
        ["python", "-m", "slurm_ci.cli", "git-watch", "stop-all"],
        capture_output=True,
        text=True,
    )

    # Command should succeed
    assert result.returncode == 0

    # Should indicate 0 daemons stopped
    assert "Stopped 0 daemon(s)" in result.stdout
