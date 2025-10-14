#!/usr/bin/env python3
"""Configuration parser for slurm-run functionality."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import toml


@dataclass
class SlurmRunConfig:
    """Configuration for a slurm-run instance."""

    # Required fields
    workflow_file: str
    working_directory: str

    # Optional fields
    slurm_options: Optional[Dict[str, Any]] = None

    @classmethod
    def from_file(cls, config_path: str) -> "SlurmRunConfig":
        """Load configuration from a TOML file."""
        config_path = Path(config_path).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            config_data = toml.load(f)

        config_dir = config_path.parent
        slurm_ci_config = config_data.get("slurm-ci", {})

        # Resolve paths to be absolute relative to the config file
        if "workflow_file" in slurm_ci_config:
            workflow_file = Path(slurm_ci_config["workflow_file"])
            if not workflow_file.is_absolute():
                slurm_ci_config["workflow_file"] = str(
                    (config_dir / workflow_file).resolve()
                )

        if "working_directory" in slurm_ci_config:
            working_directory = Path(slurm_ci_config["working_directory"])
            if not working_directory.is_absolute():
                slurm_ci_config["working_directory"] = str(
                    (config_dir / working_directory).resolve()
                )

        return cls.from_dict(config_data)

    @classmethod
    def from_dict(cls, config_data: dict) -> "SlurmRunConfig":
        """Create configuration from a dictionary."""
        slurm_ci_config = config_data.get("slurm-ci", {})

        # Validate required fields
        required_fields = {
            "slurm-ci.workflow_file": slurm_ci_config.get("workflow_file"),
            "slurm-ci.working_directory": slurm_ci_config.get("working_directory"),
        }

        missing_fields = [
            field for field, value in required_fields.items() if not value
        ]
        if missing_fields:
            raise ValueError(
                f"Missing required configuration fields: {', '.join(missing_fields)}"
            )

        return cls(
            workflow_file=slurm_ci_config["workflow_file"],
            working_directory=slurm_ci_config["working_directory"],
            slurm_options=slurm_ci_config.get("slurm"),
        )


def create_example_config(output_path: str) -> None:
    """Create an example configuration file."""
    example_config = {
        "slurm-ci": {
            "workflow_file": ".github/workflows/main.yml",
            "working_directory": ".",
            "slurm": {
                "gres": "gpu:gfx942",
                "cpus-per-task": 32,
                "time": "12:00:00",
            },
        }
    }

    output_file = Path(output_path)
    with open(output_file, "w") as f:
        toml.dump(example_config, f)

    print(f"Example configuration created at: {output_file}")
