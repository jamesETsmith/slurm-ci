#!/usr/bin/env python3
"""Configuration parser for git-watch functionality."""

import toml
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class GitWatchConfig:
    """Configuration for a git-watch daemon instance."""

    # Daemon settings
    daemon_name: str
    polling_interval: int = 300

    # Repository settings
    repo_url: str
    branch: str = "main"
    github_token: Optional[str] = None

    # Slurm settings
    config_dir: str
    workflow_file: str = ".github/workflows/ci.yml"

    @classmethod
    def from_file(cls, config_path: str) -> "GitWatchConfig":
        """Load configuration from a TOML file."""
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            config_data = toml.load(f)

        return cls.from_dict(config_data)

    @classmethod
    def from_dict(cls, config_data: dict) -> "GitWatchConfig":
        """Create configuration from a dictionary."""
        daemon_config = config_data.get("daemon", {})
        repo_config = config_data.get("repository", {})
        slurm_config = config_data.get("slurm-ci", {})

        # Validate required fields
        required_fields = {
            "daemon.name": daemon_config.get("name"),
            "repository.url": repo_config.get("url"),
            "slurm-ci.config_dir": slurm_config.get("config_dir"),
        }

        missing_fields = [
            field for field, value in required_fields.items() if not value
        ]
        if missing_fields:
            raise ValueError(
                f"Missing required configuration fields: {', '.join(missing_fields)}"
            )

        return cls(
            daemon_name=daemon_config["name"],
            polling_interval=daemon_config.get("polling_interval", 300),
            repo_url=repo_config["url"],
            branch=repo_config.get("branch", "main"),
            github_token=repo_config.get("github_token"),
            config_dir=slurm_config["config_dir"],
            workflow_file=slurm_config.get("workflow_file", ".github/workflows/ci.yml"),
        )

    def validate(self) -> None:
        """Validate the configuration."""
        if self.polling_interval < 60:
            raise ValueError("Polling interval must be at least 60 seconds")

        if not self.repo_url.startswith(("https://github.com/", "git@github.com:")):
            raise ValueError("Only GitHub repositories are currently supported")

        if not Path(self.config_dir).exists():
            raise ValueError(
                f"Slurm config directory does not exist: {self.config_dir}"
            )

    def get_repo_name(self) -> str:
        """Extract repository name from URL."""
        if self.repo_url.startswith("https://github.com/"):
            return self.repo_url.replace("https://github.com/", "").rstrip(".git")
        elif self.repo_url.startswith("git@github.com:"):
            return self.repo_url.replace("git@github.com:", "").rstrip(".git")
        else:
            raise ValueError(f"Cannot parse repository name from URL: {self.repo_url}")

    def get_working_directory(self) -> str:
        """Get the working directory for cloned repositories."""
        git_watch_dir = Path.home() / ".slurm-ci" / "git-watch"
        git_watch_dir.mkdir(parents=True, exist_ok=True)

        repo_name = self.get_repo_name().replace("/", "_")
        working_dir = git_watch_dir / "repos" / f"{repo_name}_{self.daemon_name}"
        return str(working_dir)


def create_example_config(output_path: str) -> None:
    """Create an example configuration file."""
    example_config = {
        "daemon": {
            "name": "my-project-main",
            "polling_interval": 300,
        },
        "repository": {
            "url": "https://github.com/user/repo",
            "branch": "main",
            "github_token": "optional_for_private_repos",
        },
        "slurm-ci": {
            "config_dir": "/path/to/slurm-ci-configs",
            "workflow_file": ".github/workflows/ci.yml",
        },
    }

    output_file = Path(output_path)
    with open(output_file, "w") as f:
        toml.dump(example_config, f)

    print(f"Example configuration created at: {output_file}")
