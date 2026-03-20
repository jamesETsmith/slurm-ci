"""Tests for daemon_manager.py module."""

import signal
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from slurm_ci.daemon_manager import DaemonManager
from slurm_ci.git_watch_config import GitWatchConfig


@pytest.fixture
def daemon_manager(tmp_path: Path):
    """Create a DaemonManager with temporary directories."""
    with patch("slurm_ci.daemon_manager.Path.home") as mock_home:
        mock_home.return_value = tmp_path
        manager = DaemonManager()
        yield manager


@pytest.fixture
def sample_config():
    """Create a sample GitWatchConfig for testing."""
    return GitWatchConfig(
        daemon_name="test-daemon",
        repo_url="https://github.com/user/repo",
        workflow_file="/path/to/workflow.yml",
        working_directory="/path/to/work",
        branch="main",
        polling_interval=300,
    )


class TestDaemonManagerInit:
    """Tests for DaemonManager initialization."""

    def test_init_creates_directories(self, daemon_manager: DaemonManager) -> None:
        """Test that initialization creates necessary directories."""
        assert daemon_manager.pids_dir.exists()
        assert daemon_manager.status_dir.exists()
        assert daemon_manager.logs_dir.exists()

    def test_directory_structure(self, daemon_manager: DaemonManager) -> None:
        """Test directory structure is correct."""
        assert daemon_manager.pids_dir.name == "pids"
        assert daemon_manager.status_dir.name == "status"
        assert daemon_manager.logs_dir.name == "logs"


class TestDaemonManagerPaths:
    """Tests for path generation methods."""

    def test_get_pid_file(self, daemon_manager: DaemonManager) -> None:
        """Test PID file path generation."""
        pid_file = daemon_manager.get_pid_file("test-daemon")

        assert pid_file.parent == daemon_manager.pids_dir
        assert pid_file.name == "test-daemon.pid"

    def test_get_status_file(self, daemon_manager: DaemonManager) -> None:
        """Test status file path generation."""
        status_file = daemon_manager.get_status_file("test-daemon")

        assert status_file.parent == daemon_manager.status_dir
        assert status_file.name == "test-daemon.status"

    def test_get_log_file(self, daemon_manager: DaemonManager) -> None:
        """Test log file path generation."""
        log_file = daemon_manager.get_log_file("test-daemon")

        assert log_file.parent == daemon_manager.logs_dir
        assert log_file.name == "test-daemon.log"


class TestDaemonManagerPidFile:
    """Tests for PID file operations."""

    def test_write_and_read_pid_file(self, daemon_manager: DaemonManager) -> None:
        """Test writing and reading PID file."""
        daemon_name = "test-daemon"
        pid = 12345

        daemon_manager.write_pid_file(daemon_name, pid)

        read_pid = daemon_manager.read_pid_file(daemon_name)
        assert read_pid == pid

    def test_read_nonexistent_pid_file(self, daemon_manager: DaemonManager) -> None:
        """Test reading non-existent PID file returns None."""
        pid = daemon_manager.read_pid_file("nonexistent")
        assert pid is None

    def test_remove_pid_file(self, daemon_manager: DaemonManager) -> None:
        """Test removing PID file."""
        daemon_name = "test-daemon"
        daemon_manager.write_pid_file(daemon_name, 999)

        pid_file = daemon_manager.get_pid_file(daemon_name)
        assert pid_file.exists()

        daemon_manager.remove_pid_file(daemon_name)
        assert not pid_file.exists()

    def test_read_corrupted_pid_file(self, daemon_manager: DaemonManager) -> None:
        """Test reading corrupted PID file."""
        daemon_name = "corrupted"
        pid_file = daemon_manager.get_pid_file(daemon_name)

        # Write invalid content
        with open(pid_file, "w") as f:
            f.write("not-a-number")

        pid = daemon_manager.read_pid_file(daemon_name)
        assert pid is None


class TestDaemonManagerStatusFile:
    """Tests for status file operations."""

    def test_write_and_read_status_file(
        self, daemon_manager: DaemonManager, sample_config: GitWatchConfig
    ) -> None:
        """Test writing and reading status file."""
        daemon_name = "test-daemon"
        last_check = datetime.now()
        last_commit = "abc123"

        daemon_manager.write_status_file(
            daemon_name,
            sample_config,
            status="running",
            last_check=last_check,
            last_commit=last_commit,
        )

        status = daemon_manager.read_status_file(daemon_name)

        assert status is not None
        assert status["daemon_name"] == daemon_name
        assert status["status"] == "running"
        assert status["last_commit"] == last_commit
        assert status["config"]["repo_url"] == sample_config.repo_url

    def test_read_nonexistent_status_file(self, daemon_manager: DaemonManager) -> None:
        """Test reading non-existent status file returns None."""
        status = daemon_manager.read_status_file("nonexistent")
        assert status is None

    def test_remove_status_file(
        self, daemon_manager: DaemonManager, sample_config: GitWatchConfig
    ) -> None:
        """Test removing status file."""
        daemon_name = "test-daemon"
        daemon_manager.write_status_file(daemon_name, sample_config)

        status_file = daemon_manager.get_status_file(daemon_name)
        assert status_file.exists()

        daemon_manager.remove_status_file(daemon_name)
        assert not status_file.exists()

    def test_status_file_contains_config(
        self, daemon_manager: DaemonManager, sample_config: GitWatchConfig
    ) -> None:
        """Test that status file contains config information."""
        daemon_name = "config-test"

        daemon_manager.write_status_file(daemon_name, sample_config)
        status = daemon_manager.read_status_file(daemon_name)

        assert status["config"]["repo_url"] == sample_config.repo_url
        assert status["config"]["branch"] == sample_config.branch
        assert status["config"]["polling_interval"] == sample_config.polling_interval


class TestDaemonManagerDaemonCheck:
    """Tests for daemon status checking."""

    @patch("slurm_ci.daemon_manager.psutil.Process")
    def test_is_daemon_running_true(
        self, mock_process: Mock, daemon_manager: DaemonManager
    ) -> None:
        """Test checking if daemon is running (when it is)."""
        daemon_name = "running-daemon"
        daemon_manager.write_pid_file(daemon_name, 12345)

        mock_proc = Mock()
        mock_proc.is_running.return_value = True
        mock_process.return_value = mock_proc

        assert daemon_manager.is_daemon_running(daemon_name) is True

    @patch("slurm_ci.daemon_manager.psutil.Process")
    def test_is_daemon_running_false(
        self, mock_process: Mock, daemon_manager: DaemonManager
    ) -> None:
        """Test checking if daemon is running (when it's not)."""
        daemon_name = "stopped-daemon"
        daemon_manager.write_pid_file(daemon_name, 99999)

        mock_proc = Mock()
        mock_proc.is_running.return_value = False
        mock_process.return_value = mock_proc

        assert daemon_manager.is_daemon_running(daemon_name) is False

    def test_is_daemon_running_no_pid_file(self, daemon_manager: DaemonManager) -> None:
        """Test checking daemon with no PID file."""
        assert daemon_manager.is_daemon_running("nonexistent") is False

    @patch("slurm_ci.daemon_manager.psutil.Process")
    def test_is_daemon_running_process_not_found(
        self, mock_process: Mock, daemon_manager: DaemonManager
    ) -> None:
        """Test checking daemon when process doesn't exist."""
        import psutil

        daemon_name = "dead-daemon"
        daemon_manager.write_pid_file(daemon_name, 99999)

        mock_process.side_effect = psutil.NoSuchProcess(99999)

        assert daemon_manager.is_daemon_running(daemon_name) is False


class TestDaemonManagerStopDaemon:
    """Tests for stopping daemons."""

    @patch("slurm_ci.daemon_manager.psutil.Process")
    def test_stop_daemon_success(
        self, mock_process: Mock, daemon_manager: DaemonManager
    ) -> None:
        """Test successfully stopping a daemon."""
        daemon_name = "test-daemon"
        daemon_manager.write_pid_file(daemon_name, 12345)

        mock_proc = Mock()
        mock_proc.is_running.return_value = True
        mock_proc.wait.return_value = None
        mock_process.return_value = mock_proc

        result = daemon_manager.stop_daemon(daemon_name)

        assert result is True
        mock_proc.send_signal.assert_called_with(signal.SIGTERM)
        # PID file should be removed
        assert not daemon_manager.get_pid_file(daemon_name).exists()

    def test_stop_daemon_no_pid_file(self, daemon_manager: DaemonManager) -> None:
        """Test stopping daemon with no PID file."""
        result = daemon_manager.stop_daemon("nonexistent")
        assert result is False

    @patch("slurm_ci.daemon_manager.psutil.Process")
    def test_stop_daemon_already_stopped(
        self, mock_process: Mock, daemon_manager: DaemonManager
    ) -> None:
        """Test stopping daemon that's already stopped."""
        daemon_name = "stopped-daemon"
        daemon_manager.write_pid_file(daemon_name, 99999)

        mock_proc = Mock()
        mock_proc.is_running.return_value = False
        mock_process.return_value = mock_proc

        result = daemon_manager.stop_daemon(daemon_name)

        assert result is True
        # Should clean up files
        assert not daemon_manager.get_pid_file(daemon_name).exists()


class TestDaemonManagerListDaemons:
    """Tests for listing daemons."""

    @patch("slurm_ci.daemon_manager.psutil.Process")
    def test_list_running_daemons(
        self,
        mock_process: Mock,
        daemon_manager: DaemonManager,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test listing running daemons."""
        # Create multiple daemon files
        daemon_manager.write_pid_file("daemon1", 111)
        daemon_manager.write_pid_file("daemon2", 222)
        daemon_manager.write_status_file("daemon1", sample_config)

        mock_proc = Mock()
        mock_proc.is_running.return_value = True
        mock_process.return_value = mock_proc

        daemons = daemon_manager.list_running_daemons()

        assert len(daemons) >= 1
        # At least daemon1 should be in the list
        daemon_names = [d["daemon_name"] for d in daemons]
        assert "daemon1" in daemon_names

    @patch("slurm_ci.daemon_manager.psutil.Process")
    def test_list_running_daemons_empty(
        self, mock_process: Mock, daemon_manager: DaemonManager
    ) -> None:
        """Test listing daemons when none are running."""
        daemons = daemon_manager.list_running_daemons()
        assert len(daemons) == 0


class TestDaemonManagerStopAll:
    """Tests for stopping all daemons."""

    @patch("slurm_ci.daemon_manager.psutil.Process")
    def test_stop_all_daemons(
        self, mock_process: Mock, daemon_manager: DaemonManager
    ) -> None:
        """Test stopping all running daemons."""
        # Create multiple daemon files
        daemon_manager.write_pid_file("daemon1", 111)
        daemon_manager.write_pid_file("daemon2", 222)

        mock_proc = Mock()
        mock_proc.is_running.return_value = True
        mock_proc.wait.return_value = None
        mock_process.return_value = mock_proc

        count = daemon_manager.stop_all_daemons()

        assert count == 2


class TestDaemonManagerCleanup:
    """Tests for cleanup operations."""

    def test_cleanup_daemon_files(
        self, daemon_manager: DaemonManager, sample_config: GitWatchConfig
    ) -> None:
        """Test cleaning up daemon files."""
        daemon_name = "cleanup-test"

        daemon_manager.write_pid_file(daemon_name, 999)
        daemon_manager.write_status_file(daemon_name, sample_config)

        # Verify files exist
        assert daemon_manager.get_pid_file(daemon_name).exists()
        assert daemon_manager.get_status_file(daemon_name).exists()

        daemon_manager.cleanup_daemon_files(daemon_name)

        # Verify files are removed
        assert not daemon_manager.get_pid_file(daemon_name).exists()
        assert not daemon_manager.get_status_file(daemon_name).exists()


class TestDaemonManagerSignalHandlers:
    """Tests for signal handler setup."""

    def test_setup_signal_handlers(self, daemon_manager: DaemonManager) -> None:
        """Test setting up signal handlers."""
        # This mainly tests that it doesn't crash
        # Actual signal handling is hard to test without subprocess
        daemon_name = "signal-test"

        # Should not raise an exception
        daemon_manager.setup_signal_handlers(daemon_name)
