"""Tests for config.py module."""

import os
from pathlib import Path
from unittest.mock import patch

from slurm_ci import config


class TestConfigPaths:
    """Tests for configuration path constants."""

    def test_slurm_ci_dir_exists(self) -> None:
        """Test that SLURM_CI_DIR is created."""
        assert config.SLURM_CI_DIR.exists()
        assert config.SLURM_CI_DIR.is_dir()

    def test_status_dir_created(self) -> None:
        """Test that STATUS_DIR is created."""
        status_path = Path(config.STATUS_DIR)
        assert status_path.exists()
        assert status_path.is_dir()

    def test_act_path_created(self) -> None:
        """Test that ACT_PATH is created."""
        act_path = Path(config.ACT_PATH)
        assert act_path.exists()
        assert act_path.is_dir()

    def test_git_watch_dirs_created(self) -> None:
        """Test that git-watch directories are created."""
        git_watch_path = Path(config.GIT_WATCH_DIR)
        assert git_watch_path.exists()
        assert (git_watch_path / "pids").exists()
        assert (git_watch_path / "status").exists()
        assert (git_watch_path / "logs").exists()


class TestDatabaseUrl:
    """Tests for database URL configuration."""

    def test_database_url_format(self) -> None:
        """Test that DATABASE_URL has correct format."""
        assert config.DATABASE_URL.startswith("sqlite:///")
        assert "slurm_ci.db" in config.DATABASE_URL

    def test_database_url_in_slurm_ci_dir(self) -> None:
        """Test that database is in SLURM_CI_DIR."""
        db_path = config.DATABASE_URL.replace("sqlite:///", "")
        assert str(config.SLURM_CI_DIR) in db_path


class TestActBinary:
    """Tests for ACT binary configuration."""

    def test_act_binary_path(self) -> None:
        """Test ACT binary path."""
        assert "act" in config.ACT_BINARY
        # Default should be in ACT_PATH
        if "SLURM_CI_ACT_BINARY" not in os.environ:
            assert str(config.ACT_PATH) in config.ACT_BINARY

    @patch.dict(os.environ, {"SLURM_CI_ACT_BINARY": "/custom/path/to/act"})
    def test_act_binary_custom_env(self) -> None:
        """Test ACT binary can be set via environment variable."""
        # Need to reload the module to pick up the new env var
        import importlib

        importlib.reload(config)

        assert config.ACT_BINARY == "/custom/path/to/act"

        # Clean up
        importlib.reload(config)


class TestStatusDirEnv:
    """Tests for STATUS_DIR environment variable."""

    def test_status_dir_custom_env(self, tmp_path: Path) -> None:
        """Test STATUS_DIR can be set via environment variable."""
        import importlib

        custom_dir = tmp_path / "custom_status"
        custom_dir.mkdir()

        with patch.dict(os.environ, {"SLURM_CI_STATUS_DIR": str(custom_dir)}):
            importlib.reload(config)

            assert config.STATUS_DIR == str(custom_dir)

            # Clean up
            importlib.reload(config)


class TestGitWatchDir:
    """Tests for git-watch directory configuration."""

    def test_git_watch_dir_path(self) -> None:
        """Test GIT_WATCH_DIR is in SLURM_CI_DIR."""
        assert str(config.SLURM_CI_DIR) in config.GIT_WATCH_DIR
        assert "git-watch" in config.GIT_WATCH_DIR


class TestConfigConstants:
    """Tests for various config constants."""

    def test_slurm_ci_dir_is_path(self) -> None:
        """Test SLURM_CI_DIR is a Path object."""
        assert isinstance(config.SLURM_CI_DIR, Path)

    def test_status_dir_is_string(self) -> None:
        """Test STATUS_DIR is a string."""
        assert isinstance(config.STATUS_DIR, str)

    def test_act_path_is_string(self) -> None:
        """Test ACT_PATH is a string."""
        assert isinstance(config.ACT_PATH, str)

    def test_act_binary_is_string(self) -> None:
        """Test ACT_BINARY is a string."""
        assert isinstance(config.ACT_BINARY, str)

    def test_git_watch_dir_is_string(self) -> None:
        """Test GIT_WATCH_DIR is a string."""
        assert isinstance(config.GIT_WATCH_DIR, str)
