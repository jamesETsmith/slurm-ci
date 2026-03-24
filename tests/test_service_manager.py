"""Tests for service_manager.py module."""

import signal
from pathlib import Path
from unittest.mock import Mock, patch

import psutil

from slurm_ci.service_manager import ServiceManager


def test_init_creates_directories(tmp_path: Path) -> None:
    manager = ServiceManager(base_dir=tmp_path / "services")
    assert manager.pids_dir.exists()
    assert manager.status_dir.exists()
    assert manager.logs_dir.exists()


def test_start_service_writes_pid_and_status(tmp_path: Path) -> None:
    manager = ServiceManager(base_dir=tmp_path / "services")
    command = ["python", "-V"]

    with patch("slurm_ci.service_manager.subprocess.Popen") as mock_popen:
        process = Mock()
        process.pid = 4242
        mock_popen.return_value = process

        started, reason = manager.start_service(
            "dashboard", command, metadata={"port": 5001}
        )

    assert started is True
    assert reason == "started"
    assert manager.read_pid_file("dashboard") == 4242
    status = manager.read_status_file("dashboard")
    assert status is not None
    assert status["pid"] == 4242
    assert status["metadata"]["port"] == 5001


def test_start_service_skips_when_running(tmp_path: Path) -> None:
    manager = ServiceManager(base_dir=tmp_path / "services")
    manager.write_pid_file("db-watch", 1010)

    with patch("slurm_ci.service_manager.psutil.Process") as mock_process:
        proc = Mock()
        proc.is_running.return_value = True
        mock_process.return_value = proc

        started, reason = manager.start_service("db-watch", ["python", "watch.py"])

    assert started is False
    assert reason == "already-running"


def test_is_service_running_cleans_stale_pid(tmp_path: Path) -> None:
    manager = ServiceManager(base_dir=tmp_path / "services")
    manager.write_pid_file("dashboard", 99999)

    with patch(
        "slurm_ci.service_manager.psutil.Process",
        side_effect=psutil.NoSuchProcess(99999),
    ):
        assert manager.is_service_running("dashboard") is False

    assert manager.read_pid_file("dashboard") is None


def test_stop_service_graceful(tmp_path: Path) -> None:
    manager = ServiceManager(base_dir=tmp_path / "services")
    manager.write_pid_file("dashboard", 2222)

    with patch("slurm_ci.service_manager.psutil.Process") as mock_process:
        proc = Mock()
        proc.is_running.return_value = True
        proc.wait.return_value = None
        mock_process.return_value = proc

        assert manager.stop_service("dashboard") is True

    proc.send_signal.assert_called_with(signal.SIGTERM)
    assert manager.read_pid_file("dashboard") is None


def test_stop_service_timeout_requires_force(tmp_path: Path) -> None:
    manager = ServiceManager(base_dir=tmp_path / "services")
    manager.write_pid_file("db-watch", 3333)

    with patch("slurm_ci.service_manager.psutil.Process") as mock_process:
        proc = Mock()
        proc.is_running.return_value = True
        proc.wait.side_effect = psutil.TimeoutExpired(3333, timeout=1)
        mock_process.return_value = proc

        assert manager.stop_service("db-watch", timeout=1, force=False) is False

    assert manager.read_pid_file("db-watch") == 3333
