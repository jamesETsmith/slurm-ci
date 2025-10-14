#!/usr/bin/env python3
"""Configuration parser for git-watch functionality."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import toml


@dataclass
class GitWatchConfig:
    """Configuration for a git-watch daemon instance."""

    # Required fields (no defaults)
    daemon_name: str
    repo_url: str
    config_dir: str
    working_directory: str

    # Optional fields (with defaults)
    polling_interval: int = 300
    branch: str = "main"
    github_token: Optional[str] = None
    workflow_file: str = "workflows/ci.yml"
    slurm_options: Optional[Dict[str, Any]] = None

    @classmethod
    def from_file(cls, config_path: str) -> "GitWatchConfig":
        """Load configuration from a TOML file."""
        config_path = Path(config_path).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            config_data = toml.load(f)

        config_dir = config_path.parent
        slurm_ci_config = config_data.get("slurm-ci", {})

        if "working_directory" in slurm_ci_config:
            working_directory = Path(slurm_ci_config["working_directory"])
            if not working_directory.is_absolute():
                slurm_ci_config["working_directory"] = str(
                    (config_dir / working_directory).resolve()
                )

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
            "slurm-ci.working_directory": slurm_config.get("working_directory"),
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
            working_directory=slurm_config["working_directory"],
            workflow_file=slurm_config.get("workflow_file", "workflows/ci.yml"),
            slurm_options=slurm_config.get("slurm"),
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
            "working_directory": "/path/to/working-directory",
            "workflow_file": "workflows/ci.yml",
            "slurm": {
                "gres": "gpu:gfx942",
                "cpus-per-task": 32,
                "time": "12:00:00",
                "partition": "gpu",
            },
        },
    }

    output_file = Path(output_path)
    with open(output_file, "w") as f:
        toml.dump(example_config, f)

    print(f"Example configuration created at: {output_file}")
