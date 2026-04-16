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
            "workflow_file": "workflows/test.yml",
            "working_directory": "/tmp/work-dir",
        },
    }

    config = GitWatchConfig.from_dict(config_data)

    assert config.daemon_name == "test-daemon"
    assert config.polling_interval == 600
    assert config.repo_url == "https://github.com/user/repo"
    assert config.branch == "develop"
    assert config.github_token == "test-token"
    assert config.workflow_file == "workflows/test.yml"
    assert config.working_directory == "/tmp/work-dir"


def test_config_missing_required_fields() -> None:
    """Test error handling for missing required fields."""
    config_data = {
        "daemon": {"name": "test-daemon"},
        "repository": {"url": "https://github.com/user/repo"},
        "slurm-ci": {"working_directory": "/tmp/work-dir"},
        # Missing slurm-ci.workflow_file
    }

    with pytest.raises(ValueError, match="Missing required configuration fields"):
        GitWatchConfig.from_dict(config_data)


def test_config_defaults() -> None:
    """Test default values are applied correctly."""
    config_data = {
        "daemon": {"name": "test-daemon"},
        "repository": {"url": "https://github.com/user/repo"},
        "slurm-ci": {
            "workflow_file": "workflows/ci.yml",
            "working_directory": "/tmp/work-dir",
        },
    }

    config = GitWatchConfig.from_dict(config_data)

    assert config.polling_interval == 300  # default
    assert config.branch == "main"  # default
    assert config.github_token is None  # default


def test_config_validation() -> None:
    """Test configuration validation."""
    # Test polling interval too low
    config = GitWatchConfig(
        daemon_name="test",
        polling_interval=30,  # Too low
        repo_url="https://github.com/user/repo",
        workflow_file="/tmp/test-workflow.yml",
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
        workflow_file="/tmp/test-workflow.yml",
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
        workflow_file="/tmp/test-workflow.yml",
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
workflow_file = "workflows/test.yml"
working_directory = "/tmp/work-dir"
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
            assert config.workflow_file.endswith("workflows/test.yml")
            assert config.working_directory.endswith("/tmp/work-dir")
        finally:
            os.unlink(f.name)


def test_config_file_not_found(tmp_path) -> None:
    """Test error handling for missing configuration file."""
    missing_file = tmp_path / "missing-config.toml"
    with pytest.raises(FileNotFoundError):
        GitWatchConfig.from_file(str(missing_file))


class TestBranchesList:
    def test_branches_list_parses(self) -> None:
        config = GitWatchConfig.from_dict(
            {
                "daemon": {"name": "d"},
                "repository": {
                    "url": "https://github.com/user/repo",
                    "branches": ["main", "release/*"],
                },
                "slurm-ci": {
                    "workflow_file": "w.yml",
                    "working_directory": "/tmp",
                },
            }
        )
        assert config.branches == ["main", "release/*"]
        assert config.branch == "main"  # default scalar untouched
        assert config.branch_label() == "main,release/*"
        patterns = config.ref_patterns()
        assert patterns.include == (
            "refs/heads/main",
            "refs/heads/release/*",
        )

    def test_empty_branches_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty list"):
            GitWatchConfig.from_dict(
                {
                    "daemon": {"name": "d"},
                    "repository": {
                        "url": "https://github.com/user/repo",
                        "branches": [],
                    },
                    "slurm-ci": {
                        "workflow_file": "w.yml",
                        "working_directory": "/tmp",
                    },
                }
            )

    def test_non_string_branches_rejected(self) -> None:
        with pytest.raises(ValueError, match="must all be strings"):
            GitWatchConfig.from_dict(
                {
                    "daemon": {"name": "d"},
                    "repository": {
                        "url": "https://github.com/user/repo",
                        "branches": ["main", 123],
                    },
                    "slurm-ci": {
                        "workflow_file": "w.yml",
                        "working_directory": "/tmp",
                    },
                }
            )


class TestRefsTable:
    def _base(self, refs: dict) -> dict:
        return {
            "daemon": {"name": "d"},
            "repository": {
                "url": "https://github.com/user/repo",
                "refs": refs,
            },
            "slurm-ci": {
                "workflow_file": "w.yml",
                "working_directory": "/tmp",
            },
        }

    def test_include_exclude_and_match_style(self) -> None:
        config = GitWatchConfig.from_dict(
            self._base(
                {
                    "include": ["main", "refs/tags/v*"],
                    "exclude": ["release/*-rc*"],
                    "match_style": "git",
                }
            )
        )
        assert config.refs_include == ["main", "refs/tags/v*"]
        assert config.refs_exclude == ["release/*-rc*"]
        assert config.match_style == "git"

        patterns = config.ref_patterns()
        assert patterns.include == ("refs/heads/main", "refs/tags/v*")
        assert patterns.exclude == ("refs/heads/release/*-rc*",)
        assert patterns.match_style == "git"
        assert patterns.matches("refs/heads/main")
        assert patterns.matches("refs/tags/v1.0")
        assert not patterns.matches("refs/heads/release/1.0-rc1")

    def test_include_required(self) -> None:
        with pytest.raises(ValueError, match="refs.include"):
            GitWatchConfig.from_dict(self._base({"exclude": ["x"]}))

    def test_match_style_validated(self) -> None:
        with pytest.raises(ValueError, match="match_style"):
            GitWatchConfig.from_dict(
                self._base({"include": ["main"], "match_style": "regex"})
            )

    def test_refs_must_be_table(self) -> None:
        with pytest.raises(ValueError, match="must be a table"):
            GitWatchConfig.from_dict(
                {
                    "daemon": {"name": "d"},
                    "repository": {
                        "url": "https://github.com/user/repo",
                        "refs": "nope",
                    },
                    "slurm-ci": {
                        "workflow_file": "w.yml",
                        "working_directory": "/tmp",
                    },
                }
            )

    def test_branch_label_includes_exclude(self) -> None:
        config = GitWatchConfig.from_dict(
            self._base(
                {
                    "include": ["release/*"],
                    "exclude": ["release/*-rc*"],
                }
            )
        )
        assert config.branch_label() == "release/* !(release/*-rc*)"


class TestMutualExclusivity:
    def test_branch_and_branches_rejected(self) -> None:
        with pytest.raises(ValueError, match="at most one"):
            GitWatchConfig.from_dict(
                {
                    "daemon": {"name": "d"},
                    "repository": {
                        "url": "https://github.com/user/repo",
                        "branch": "main",
                        "branches": ["main", "release/*"],
                    },
                    "slurm-ci": {
                        "workflow_file": "w.yml",
                        "working_directory": "/tmp",
                    },
                }
            )

    def test_branches_and_refs_rejected(self) -> None:
        with pytest.raises(ValueError, match="at most one"):
            GitWatchConfig.from_dict(
                {
                    "daemon": {"name": "d"},
                    "repository": {
                        "url": "https://github.com/user/repo",
                        "branches": ["main"],
                        "refs": {"include": ["main"]},
                    },
                    "slurm-ci": {
                        "workflow_file": "w.yml",
                        "working_directory": "/tmp",
                    },
                }
            )


class TestLegacyBranchStillWorks:
    def test_default_branch_produces_heads_main_pattern(self) -> None:
        config = GitWatchConfig.from_dict(
            {
                "daemon": {"name": "d"},
                "repository": {"url": "https://github.com/user/repo"},
                "slurm-ci": {
                    "workflow_file": "w.yml",
                    "working_directory": "/tmp",
                },
            }
        )
        assert config.branch == "main"
        assert config.branches is None
        assert config.refs_include is None
        assert config.branch_label() == "main"
        assert config.ref_patterns().include == ("refs/heads/main",)

    def test_scalar_wildcard_branch(self) -> None:
        config = GitWatchConfig.from_dict(
            {
                "daemon": {"name": "d"},
                "repository": {
                    "url": "https://github.com/user/repo",
                    "branch": "release/*",
                },
                "slurm-ci": {
                    "workflow_file": "w.yml",
                    "working_directory": "/tmp",
                },
            }
        )
        assert config.branch == "release/*"
        assert config.branch_label() == "release/*"
        assert config.ref_patterns().include == ("refs/heads/release/*",)


class TestValidateWithNewForms:
    def test_empty_refs_include_falls_through_to_branch(self) -> None:
        """An empty ``refs_include`` is treated as 'not set' and falls back
        to the scalar ``branch`` field."""
        config = GitWatchConfig(
            daemon_name="d",
            repo_url="https://github.com/user/repo",
            workflow_file="/tmp/w.yml",
            working_directory="/tmp",
            refs_include=[],
        )
        config.validate()
        assert config.ref_patterns().include == ("refs/heads/main",)

    def test_validate_rejects_unknown_match_style_via_direct_construction(
        self,
    ) -> None:
        config = GitWatchConfig(
            daemon_name="d",
            repo_url="https://github.com/user/repo",
            workflow_file="/tmp/w.yml",
            working_directory="/tmp",
            match_style="regex",  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError):
            config.validate()
