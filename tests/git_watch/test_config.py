#!/usr/bin/env python3
"""Tests for git-watch configuration parsing."""

import os
import tempfile

import pytest

from slurm_ci.git_watch_config import GitWatchConfig


def test_config_from_dict() -> None:
    """Test creating configuration from dictionary."""
    config_data = {
        "daemon": {"name": "test-daemon", "polling_interval": 600},
        "repository": {
            "url": "https://github.com/user/repo",
            "branch": "develop",
            "github_token": "test-token",
        },
        "slurm-ci": {
            "config_dir": "/tmp/test-config",
            "working_directory": "/tmp/work-dir",
            "workflow_file": "workflows/test.yml",
        },
    }

    config = GitWatchConfig.from_dict(config_data)

    assert config.daemon_name == "test-daemon"
    assert config.polling_interval == 600
    assert config.repo_url == "https://github.com/user/repo"
    assert config.branch == "develop"
    assert config.github_token == "test-token"
    assert config.config_dir == "/tmp/test-config"
    assert config.working_directory == "/tmp/work-dir"
    assert config.workflow_file == "workflows/test.yml"


def test_config_missing_required_fields() -> None:
    """Test error handling for missing required fields."""
    config_data = {
        "daemon": {"name": "test-daemon"},
        "repository": {"url": "https://github.com/user/repo"},
        "slurm-ci": {"config_dir": "/tmp/test-config"},
        # Missing slurm-ci.working_directory
    }

    with pytest.raises(ValueError, match="Missing required configuration fields"):
        GitWatchConfig.from_dict(config_data)


def test_config_defaults() -> None:
    """Test default values are applied correctly."""
    config_data = {
        "daemon": {"name": "test-daemon"},
        "repository": {"url": "https://github.com/user/repo"},
        "slurm-ci": {
            "config_dir": "/tmp/test-config",
            "working_directory": "/tmp/work-dir",
        },
    }

    config = GitWatchConfig.from_dict(config_data)

    assert config.polling_interval == 300  # default
    assert config.branch == "main"  # default
    assert config.workflow_file == "workflows/ci.yml"  # default
    assert config.github_token is None  # default


def test_config_validation() -> None:
    """Test configuration validation."""
    # Test polling interval too low
    config = GitWatchConfig(
        daemon_name="test",
        polling_interval=30,  # Too low
        repo_url="https://github.com/user/repo",
        config_dir="/tmp/test",
        working_directory="/tmp/work-dir",
    )

    with pytest.raises(
        ValueError, match="Polling interval must be at least 60 seconds"
    ):
        config.validate()

    # Test invalid repository URL
    config = GitWatchConfig(
        daemon_name="test",
        polling_interval=300,
        repo_url="https://gitlab.com/user/repo",  # Not GitHub
        config_dir="/tmp/test",
        working_directory="/tmp/work-dir",
    )

    with pytest.raises(
        ValueError, match="Only GitHub repositories are currently supported"
    ):
        config.validate()


def test_get_repo_name() -> None:
    """Test repository name extraction."""
    config = GitWatchConfig(
        daemon_name="test",
        repo_url="https://github.com/user/repo",
        config_dir="/tmp/test",
        working_directory="/tmp/work-dir",
    )

    assert config.get_repo_name() == "user/repo"

    # Test with .git suffix
    config.repo_url = "https://github.com/user/repo.git"
    assert config.get_repo_name() == "user/repo"

    # Test SSH URL
    config.repo_url = "git@github.com:user/repo.git"
    assert config.get_repo_name() == "user/repo"


def test_config_from_file() -> None:
    """Test loading configuration from TOML file."""
    config_content = """
[daemon]
name = "test-daemon"
polling_interval = 600

[repository]
url = "https://github.com/user/repo"
branch = "develop"

[slurm-ci]
config_dir = "/tmp/test-config"
working_directory = "/tmp/work-dir"
workflow_file = "workflows/test.yml"
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(config_content)
        f.flush()

        try:
            config = GitWatchConfig.from_file(f.name)

            assert config.daemon_name == "test-daemon"
            assert config.polling_interval == 600
            assert config.repo_url == "https://github.com/user/repo"
            assert config.branch == "develop"
            assert config.config_dir == "/tmp/test-config"
            assert config.working_directory == "/tmp/work-dir"
            assert config.workflow_file == "workflows/test.yml"
        finally:
            os.unlink(f.name)


def test_config_file_not_found() -> None:
    """Test error handling for missing configuration file."""
    with pytest.raises(FileNotFoundError):
        GitWatchConfig.from_file("/nonexistent/config.toml")
