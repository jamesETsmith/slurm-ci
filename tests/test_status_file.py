"""Tests for status_file.py module."""

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from slurm_ci.status_file import StatusFile


@pytest.fixture
def mock_git_commands() -> Mock:
    """Mock all git subprocess calls."""
    with patch("slurm_ci.status_file.subprocess.check_output") as mock:
        # Need to set up side_effect to handle multiple calls
        def git_mock_side_effect(cmd, *args, **kwargs):
            # Determine which git command is being called
            if (
                "rev-parse" in cmd
                and "HEAD" in cmd
                and "--abbrev-ref" not in cmd
                and "--show-toplevel" not in cmd
            ):
                return b"abc123def456\n"  # git rev-parse HEAD
            elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                return b"/tmp/test-project\n"  # git rev-parse --show-toplevel
            elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return b"main\n"  # git rev-parse --abbrev-ref HEAD
            else:
                return b""

        mock.side_effect = git_mock_side_effect
        yield mock


@pytest.fixture
def temp_workflow_file(tmp_path: Path) -> Path:
    """Create a temporary workflow file."""
    workflow = tmp_path / "workflow.yml"
    workflow.write_text("name: test\njobs:\n  test:\n    runs-on: ubuntu")
    return workflow


class TestStatusFileCreation:
    """Tests for StatusFile creation and initialization."""

    def test_basic_creation(
        self, mock_git_commands: Mock, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test basic status file creation."""
        sf = StatusFile(
            workflow_file=str(temp_workflow_file),
            working_directory=str(tmp_path),
            matrix_args={"python-version": "3.9", "os": "ubuntu-latest"},
        )

        assert sf.data["project"]["name"] == "test-project"
        assert sf.data["project"]["workflow_file"] == str(temp_workflow_file)
        assert sf.data["project"]["working_directory"] == str(tmp_path)
        assert sf.data["git"]["commit"] == "abc123def456"  # pragma: allowlist secret
        assert sf.data["git"]["branch"] == "main"
        assert sf.data["matrix"]["python-version"] == "3.9"
        assert sf.data["matrix"]["os"] == "ubuntu-latest"

    def test_creation_with_git_repo_url(
        self, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test status file creation with git repository URL."""
        with patch("slurm_ci.status_file.subprocess.check_output") as mock:
            mock.return_value = b"remote123\t\n"

            sf = StatusFile(
                workflow_file=str(temp_workflow_file),
                working_directory=str(tmp_path),
                matrix_args={"version": "1.0"},
                git_repo_url="https://github.com/user/repo",
                git_repo_branch="develop",
            )

            assert sf.git_repo_url == "https://github.com/user/repo"
            assert sf.git_repo_branch == "develop"
            assert sf.data["git"]["branch"] == "develop"
            assert sf.data["project"]["name"] == "repo"

    def test_hashed_filename_generation(
        self, mock_git_commands: Mock, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test that hashed filename is generated correctly."""
        sf = StatusFile(
            workflow_file=str(temp_workflow_file),
            working_directory=str(tmp_path),
            matrix_args={"key": "value"},
        )

        # Verify it's a valid hex string
        assert len(sf.hashed_filename) == 64
        assert all(c in "0123456789abcdef" for c in sf.hashed_filename)

        # Verify status file path
        assert sf.hashed_filename in sf.status_file
        assert sf.status_file.endswith(".toml")


class TestStatusFileWriteRead:
    """Tests for writing and reading status files."""

    def test_write_and_read(
        self, mock_git_commands: Mock, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test writing and reading status file."""
        with patch("slurm_ci.config.STATUS_DIR", str(tmp_path / "status")):
            sf = StatusFile(
                workflow_file=str(temp_workflow_file),
                working_directory=str(tmp_path),
                matrix_args={"version": "1.0"},
            )

            sf.write()

            # Verify file exists
            assert os.path.exists(sf.status_file)

            # Read back data
            read_data = sf.read()
            assert read_data["project"]["name"] == "test-project"
            assert read_data["matrix"]["version"] == "1.0"

    def test_from_file(
        self, mock_git_commands: Mock, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test loading StatusFile from an existing file."""
        with patch("slurm_ci.config.STATUS_DIR", str(tmp_path / "status")):
            # Create and write original
            sf1 = StatusFile(
                workflow_file=str(temp_workflow_file),
                working_directory=str(tmp_path),
                matrix_args={"key": "value"},
            )
            sf1.write()

            # Load from file
            sf2 = StatusFile.from_file(sf1.status_file)

            # TOML deserialization drops explicit None values in nested tables.
            assert sf2.data["project"] == sf1.data["project"]
            assert sf2.data["git"] == sf1.data["git"]
            assert sf2.data["matrix"] == sf1.data["matrix"]
            assert sf2.data["ci"] == sf1.data["ci"]
            assert sf2.data["runtime"] == sf1.data["runtime"]
            assert sf2.status_file == sf1.status_file


class TestStatusFileGitMethods:
    """Tests for git-related methods."""

    def test_get_git_hash_local(self, temp_workflow_file: Path, tmp_path: Path) -> None:
        """Test getting git hash from local repository."""
        with patch("slurm_ci.status_file.subprocess.check_output") as mock:

            def git_mock_side_effect(cmd, *args, **kwargs):
                if (
                    "rev-parse" in cmd
                    and "HEAD" in cmd
                    and "--abbrev-ref" not in cmd
                    and "--show-toplevel" not in cmd
                ):
                    return b"local_hash_123\n"
                elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                    return b"/tmp/project\n"
                elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                    return b"main\n"
                return b""

            mock.side_effect = git_mock_side_effect

            sf = StatusFile(
                workflow_file=str(temp_workflow_file),
                working_directory=str(tmp_path),
                matrix_args={},
            )

            # Hash was called during init
            assert sf.data["git"]["commit"] == "local_hash_123"

    def test_get_git_hash_remote(
        self, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test getting git hash from remote repository."""
        with patch("slurm_ci.status_file.subprocess.check_output") as mock:
            mock.return_value = b"remote_hash_456\tHEAD\n"

            sf = StatusFile(
                workflow_file=str(temp_workflow_file),
                working_directory=str(tmp_path),
                matrix_args={},
                git_repo_url="https://github.com/user/repo",
                git_repo_branch="main",
            )

            assert sf.data["git"]["commit"] == "remote_hash_456"

    def test_get_project_name_from_url(
        self, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test extracting project name from git URL."""
        with patch("slurm_ci.status_file.subprocess.check_output") as mock:
            mock.return_value = b"hash\tHEAD\n"

            sf = StatusFile(
                workflow_file=str(temp_workflow_file),
                working_directory=str(tmp_path),
                matrix_args={},
                git_repo_url="https://github.com/user/my-project.git",
                git_repo_branch="main",
            )

            assert sf.data["project"]["name"] == "my-project"

    def test_get_project_name_local(
        self, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test getting project name from local git repo."""
        with patch("slurm_ci.status_file.subprocess.check_output") as mock:

            def git_mock_side_effect(cmd, *args, **kwargs):
                if (
                    "rev-parse" in cmd
                    and "HEAD" in cmd
                    and "--abbrev-ref" not in cmd
                    and "--show-toplevel" not in cmd
                ):
                    return b"hash123\n"
                elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                    return b"/path/to/my-local-project\n"
                elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                    return b"develop\n"
                return b""

            mock.side_effect = git_mock_side_effect

            sf = StatusFile(
                workflow_file=str(temp_workflow_file),
                working_directory=str(tmp_path),
                matrix_args={},
            )

            assert sf.data["project"]["name"] == "my-local-project"


class TestStatusFileLogfilePath:
    """Tests for logfile path generation."""

    def test_get_logfile_path(
        self, mock_git_commands: Mock, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test logfile path generation."""
        sf = StatusFile(
            workflow_file=str(temp_workflow_file),
            working_directory=str(tmp_path),
            matrix_args={"key": "value"},
        )

        logfile_path = sf.get_logfile_path()

        # Should use the same hash
        assert sf.hashed_filename in logfile_path
        # Should have .log extension
        assert logfile_path.endswith(".log")
        # Should be a valid path
        assert os.path.isabs(logfile_path)

    def test_logfile_path_in_data(
        self, mock_git_commands: Mock, temp_workflow_file: Path, tmp_path: Path
    ) -> None:
        """Test that logfile path is stored in data."""
        sf = StatusFile(
            workflow_file=str(temp_workflow_file),
            working_directory=str(tmp_path),
            matrix_args={},
        )

        assert "logfile_path" in sf.data["ci"]
        assert sf.data["ci"]["logfile_path"] == sf.get_logfile_path()
