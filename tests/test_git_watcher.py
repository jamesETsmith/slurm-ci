"""Tests for git_watcher.py module with mocked job triggering."""

import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from slurm_ci.database import CommitStatus
from slurm_ci.git_watch_config import GitWatchConfig
from slurm_ci.git_watcher import GitWatcher, start_git_watcher


@pytest.fixture
def sample_config(tmp_path: Path):
    """Create a sample GitWatchConfig for testing."""
    workflow_file = tmp_path / "workflow.yml"
    workflow_file.write_text("name: test\njobs:\n  test:\n    runs-on: ubuntu")

    return GitWatchConfig(
        daemon_name="test-watcher",
        repo_url="https://github.com/user/repo",
        workflow_file=str(workflow_file),
        working_directory=str(tmp_path / "work"),
        branch="main",
        polling_interval=300,
    )


@pytest.fixture
def mock_database():
    """Mock database session."""
    with patch("slurm_ci.git_watcher.SessionLocal") as mock_session_class:
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        yield mock_session


@pytest.fixture
def mock_daemon_manager():
    """Mock DaemonManager."""
    with patch("slurm_ci.git_watcher.DaemonManager") as mock_dm_class:
        mock_dm = Mock()
        mock_dm_class.return_value = mock_dm
        yield mock_dm


@pytest.fixture(autouse=True)
def mock_logging_handlers() -> None:
    """Prevent file-based logger setup from touching real filesystem paths."""
    with (
        patch(
            "slurm_ci.git_watcher.logging.FileHandler",
            return_value=logging.NullHandler(),
        ),
        patch(
            "slurm_ci.git_watcher.logging.StreamHandler",
            return_value=logging.NullHandler(),
        ),
    ):
        yield


class TestGitWatcherInit:
    """Tests for GitWatcher initialization."""

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_init_basic(
        self,
        mock_dm_class: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
        tmp_path: Path,
    ) -> None:
        """Test basic GitWatcher initialization."""
        # Setup DaemonManager mock
        mock_dm = Mock()
        mock_dm.get_log_file.return_value = tmp_path / "test.log"
        mock_dm_class.return_value = mock_dm

        mock_session = Mock()
        mock_session_class.return_value = mock_session

        # Mock query for existing repo
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)

        assert watcher.config == sample_config
        assert watcher.session is not None

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_init_with_github_token(
        self,
        mock_dm_class: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
        tmp_path: Path,
    ) -> None:
        """Test initialization with GitHub token."""
        # Setup DaemonManager mock
        mock_dm = Mock()
        mock_dm.get_log_file.return_value = tmp_path / "test.log"
        mock_dm_class.return_value = mock_dm

        sample_config.github_token = "test-token"

        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)

        # Check that Authorization header is set
        assert "Authorization" in watcher.session.headers


class TestGitWatcherFetchCommit:
    """Tests for fetching latest commit."""

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    @patch("slurm_ci.git_watcher.subprocess.check_output")
    def test_fetch_latest_commit_success(
        self,
        mock_check_output: Mock,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test fetching latest commit successfully."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        mock_check_output.return_value = (
            b"abc123def456\trefs/heads/main\n"  # pragma: allowlist secret
        )

        watcher = GitWatcher(sample_config)
        commit = watcher._fetch_latest_commit()

        assert commit == "abc123def456"  # pragma: allowlist secret

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    @patch("slurm_ci.git_watcher.subprocess.check_output")
    def test_fetch_latest_commit_error(
        self,
        mock_check_output: Mock,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test handling error when fetching commit."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        mock_check_output.side_effect = Exception("Git error")

        watcher = GitWatcher(sample_config)
        commit = watcher._fetch_latest_commit()

        assert commit is None

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    @patch("slurm_ci.git_watcher.subprocess.check_output")
    def test_fetch_latest_commits_wildcard_branch(
        self,
        mock_check_output: Mock,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test fetching branch heads for wildcard branch patterns."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        sample_config.branch = "release/*"
        mock_check_output.return_value = (
            b"111111111111\trefs/heads/release/1.0\n"
            b"222222222222\trefs/heads/release/2.0\n"
            b"333333333333\trefs/heads/main\n"
        )

        watcher = GitWatcher(sample_config)
        commits = watcher._fetch_latest_commits()

        assert commits == [
            ("111111111111", "release/1.0"),
            ("222222222222", "release/2.0"),
        ]


class TestGitWatcherShouldProcessCommit:
    """Tests for determining if a commit should be processed."""

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_should_process_new_commit(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test that new commits should be processed."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        # Setup: no existing tracker
        mock_repo = Mock()
        mock_repo.id = 1

        mock_query = Mock()
        mock_query.filter.return_value.first.side_effect = [None, mock_repo, None]
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        should_process = watcher._should_process_commit("new_commit_sha")

        assert should_process is True

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_should_not_process_running_commit(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test that running commits should not be reprocessed."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_repo = Mock()
        mock_repo.id = 1

        mock_tracker = Mock()
        mock_tracker.status = CommitStatus.RUNNING.value

        mock_query = Mock()
        mock_query.filter.return_value.first.side_effect = [
            None,
            mock_repo,
            mock_tracker,
        ]
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        should_process = watcher._should_process_commit("running_commit_sha")

        assert should_process is False

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_should_process_exception_commit(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test that commits with exceptions should be reprocessed."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_repo = Mock()
        mock_repo.id = 1

        mock_tracker = Mock()
        mock_tracker.status = CommitStatus.EXCEPTION.value

        mock_query = Mock()
        mock_query.filter.return_value.first.side_effect = [
            None,
            mock_repo,
            mock_tracker,
        ]
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        should_process = watcher._should_process_commit("exception_commit_sha")

        assert should_process is True


class TestGitWatcherUpdateCommitStatus:
    """Tests for updating commit status."""

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_update_commit_status_new_tracker(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test creating a new commit tracker."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_repo = Mock()
        mock_repo.id = 1

        mock_query = Mock()
        # First call returns None (init), then repo, then no tracker.
        mock_query.filter.return_value.first.side_effect = [None, mock_repo, None]
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        watcher._update_commit_status(
            "new_sha", CommitStatus.RUNNING, build_triggered=True
        )

        # Verify that session.add was called with a CommitTracker
        mock_session.add.assert_called()

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_update_commit_status_existing_tracker(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test updating an existing commit tracker."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_repo = Mock()
        mock_repo.id = 1

        mock_tracker = Mock()
        mock_tracker.status = CommitStatus.RUNNING.value

        mock_query = Mock()
        mock_query.filter.return_value.first.side_effect = [
            None,
            mock_repo,
            mock_tracker,
        ]
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        watcher._update_commit_status("existing_sha", CommitStatus.COMPLETED)

        # Verify tracker status was updated
        assert mock_tracker.status == CommitStatus.COMPLETED.value


class TestGitWatcherTriggerCiJob:
    """Tests for triggering CI jobs - with mocked launch_slurm_jobs."""

    @patch("slurm_ci.git_watcher.launch_slurm_jobs")
    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_trigger_ci_job_success(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        mock_launch: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test successfully triggering a CI job."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        result = watcher._trigger_ci_job("abc123")

        assert result is True
        # Verify launch_slurm_jobs was called with correct args
        mock_launch.assert_called_once()
        call_kwargs = mock_launch.call_args[1]
        assert call_kwargs["git_repo"]["commit_sha"] == "abc123"
        assert call_kwargs["git_repo"]["url"] == sample_config.repo_url

    @patch("slurm_ci.git_watcher.launch_slurm_jobs")
    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_trigger_ci_job_workflow_not_found(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        mock_launch: Mock,
        sample_config: GitWatchConfig,
        tmp_path: Path,
    ) -> None:
        """Test handling when workflow file doesn't exist."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        # Set workflow to non-existent file
        sample_config.workflow_file = str(tmp_path / "nonexistent.yml")

        watcher = GitWatcher(sample_config)
        result = watcher._trigger_ci_job("abc123")

        assert result is False
        mock_launch.assert_not_called()

    @patch("slurm_ci.git_watcher.launch_slurm_jobs")
    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_trigger_ci_job_with_slurm_options(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        mock_launch: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test triggering CI job with custom SLURM options."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        sample_config.slurm_options = {"partition": "gpu", "time": "02:00:00"}

        watcher = GitWatcher(sample_config)
        result = watcher._trigger_ci_job("xyz789")

        assert result is True
        call_kwargs = mock_launch.call_args[1]
        assert call_kwargs["custom_sbatch_options"] == sample_config.slurm_options


class TestGitWatcherPollOnce:
    """Tests for the polling cycle."""

    @patch("slurm_ci.git_watcher.launch_slurm_jobs")
    @patch("slurm_ci.git_watcher.subprocess.check_output")
    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_poll_once_new_commit(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        mock_check_output: Mock,
        mock_launch: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test polling cycle with a new commit."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        # Mock git ls-remote
        mock_check_output.return_value = b"new_commit_sha\trefs/heads/main\n"

        mock_repo = Mock()
        mock_repo.id = 1

        mock_query = Mock()
        # Setup query mocks for various database calls
        mock_query.filter.return_value.first.side_effect = [
            None,  # init: no existing repo
            [],  # check_running_jobs: no running commits
            mock_repo,  # should_process_commit: get repo
            None,  # should_process_commit: no tracker for commit
            mock_repo,  # update_commit_status: get repo
            None,  # update_commit_status: no tracker
        ]
        mock_query.filter.return_value.all.return_value = []  # no running commits
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        watcher._poll_once()

        # Verify job was triggered
        mock_launch.assert_called_once()

    @patch("slurm_ci.git_watcher.subprocess.check_output")
    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_poll_once_fetch_error(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        mock_check_output: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test polling when fetching commit fails."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_check_output.side_effect = Exception("Network error")

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_query.filter.return_value.all.return_value = []
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        # Should not crash
        watcher._poll_once()

    @patch("slurm_ci.git_watcher.launch_slurm_jobs")
    @patch("slurm_ci.git_watcher.subprocess.check_output")
    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_poll_once_wildcard_processes_multiple_branches(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        mock_check_output: Mock,
        mock_launch: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test polling triggers CI for each matching wildcard branch head."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        sample_config.branch = "release/*"

        mock_check_output.return_value = (
            b"aaa111\trefs/heads/release/1.0\nbbb222\trefs/heads/release/2.0\n"
        )

        mock_repo = Mock()
        mock_repo.id = 1

        mock_query = Mock()
        mock_query.filter.return_value.first.side_effect = [
            None,  # init: no existing repo
            mock_repo,  # should_process_commit for first branch commit
            None,  # no tracker for first commit
            mock_repo,  # update_commit_status for first branch commit
            None,  # no tracker for first commit status update
            mock_repo,  # should_process_commit for second branch commit
            None,  # no tracker for second commit
            mock_repo,  # update_commit_status for second branch commit
            None,  # no tracker for second commit status update
        ]
        mock_query.filter.return_value.all.return_value = []  # no running commits
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        watcher._poll_once()

        assert mock_launch.call_count == 2
        first_call = mock_launch.call_args_list[0][1]
        second_call = mock_launch.call_args_list[1][1]
        assert first_call["git_repo_branch"] == "release/1.0"
        assert second_call["git_repo_branch"] == "release/2.0"


class TestGitWatcherCheckRunningJobs:
    """Tests for checking running jobs."""

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    @patch("slurm_ci.config.STATUS_DIR", "/tmp/test-status")
    def test_check_running_jobs_no_running(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test checking when no jobs are running."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_repo = Mock()
        mock_repo.id = 1

        mock_query = Mock()
        mock_query.filter.return_value.first.side_effect = [None, mock_repo]
        mock_query.filter.return_value.all.return_value = []  # no running commits
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        # Should not crash when no running jobs
        watcher._check_running_jobs()


class TestGitWatcherSetupDatabase:
    """Tests for database setup."""

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_setup_database_creates_repo(
        self,
        mock_dm: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
    ) -> None:
        """Test that database setup creates a repo entry."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None  # no existing repo
        mock_session.query.return_value = mock_query

        GitWatcher(sample_config)

        # Verify session.add was called (repo was created)
        mock_session.add.assert_called()
        mock_session.commit.assert_called()


class TestGitWatcherRunAndHelpers:
    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_run_handles_keyboard_interrupt_and_cleans_up(
        self,
        mock_dm_class: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
        tmp_path: Path,
    ) -> None:
        mock_dm = Mock()
        mock_dm.get_log_file.return_value = tmp_path / "watcher.log"
        mock_dm_class.return_value = mock_dm

        mock_session = Mock()
        mock_session_class.return_value = mock_session
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)
        watcher._poll_once = Mock(side_effect=KeyboardInterrupt())

        watcher.run()

        mock_dm.setup_signal_handlers.assert_called_once_with(sample_config.daemon_name)
        mock_dm.write_pid_file.assert_called_once()
        mock_dm.cleanup_daemon_files.assert_called_once_with(sample_config.daemon_name)

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    @patch("slurm_ci.config.STATUS_DIR", "/tmp/test-status-dir")
    def test_find_status_files_for_commit_matches_prefix(
        self,
        mock_dm_class: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
        tmp_path: Path,
    ) -> None:
        mock_dm = Mock()
        mock_dm.get_log_file.return_value = tmp_path / "watcher.log"
        mock_dm_class.return_value = mock_dm

        mock_session = Mock()
        mock_session_class.return_value = mock_session
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)

        matching = tmp_path / "match.toml"
        matching.write_text(
            '[git]\ncommit = "abcdef1234567890"\n'  # pragma: allowlist secret
        )
        non_matching = tmp_path / "nope.toml"
        non_matching.write_text('[git]\ncommit = "1111111111111111"\n')
        bad = tmp_path / "bad.toml"
        bad.write_text("invalid=[")

        with patch("slurm_ci.config.STATUS_DIR", str(tmp_path)):
            results = watcher._find_status_files_for_commit("abcdef12")

        assert matching in results
        assert non_matching not in results

    @patch("slurm_ci.git_watcher.init_db")
    @patch("slurm_ci.git_watcher.SessionLocal")
    @patch("slurm_ci.git_watcher.DaemonManager")
    def test_check_running_jobs_marks_completed(
        self,
        mock_dm_class: Mock,
        mock_session_class: Mock,
        mock_init_db: Mock,
        sample_config: GitWatchConfig,
        tmp_path: Path,
    ) -> None:
        mock_dm = Mock()
        mock_dm.get_log_file.return_value = tmp_path / "watcher.log"
        mock_dm_class.return_value = mock_dm

        mock_session = Mock()
        mock_session_class.return_value = mock_session

        repo = Mock()
        repo.id = 1
        tracker = Mock()
        tracker.commit_sha = "abcdef1234567890"  # pragma: allowlist secret

        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = repo
        mock_query.filter.return_value.all.return_value = [tracker]
        mock_session.query.return_value = mock_query

        watcher = GitWatcher(sample_config)

        status_file = tmp_path / "status.toml"
        status_file.write_text(
            "\n".join(
                [
                    "[runtime]",
                    "start_time = 100",
                    "[runtime.end]",
                    "time = 200",
                    "exit_code = 0",
                ]
            )
        )

        with (
            patch.object(
                watcher, "_find_status_files_for_commit", return_value=[status_file]
            ),
            patch.object(watcher, "_update_commit_status") as mock_update,
        ):
            watcher._check_running_jobs()
            mock_update.assert_called_once_with(
                "abcdef1234567890",  # pragma: allowlist secret
                CommitStatus.COMPLETED,
            )

    def test_start_git_watcher_exits_on_error(self) -> None:
        with patch(
            "slurm_ci.git_watcher.GitWatchConfig.from_file",
            side_effect=ValueError("bad config"),
        ):
            with pytest.raises(SystemExit):
                start_git_watcher("/tmp/missing.toml")
