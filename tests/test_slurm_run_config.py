"""Tests for slurm_run_config.py module."""

from pathlib import Path

import pytest
import toml

from slurm_ci.slurm_run_config import (
    SlurmRunConfig,
    apply_matrix_mappings,
    create_example_config,
)


class TestSlurmRunConfig:
    """Tests for SlurmRunConfig class."""

    def test_from_dict_basic(self) -> None:
        """Test creating config from dictionary."""
        config_data = {
            "slurm-ci": {
                "workflow_file": "/path/to/workflow.yml",
                "working_directory": "/path/to/work",
            }
        }

        config = SlurmRunConfig.from_dict(config_data)

        assert config.workflow_file == "/path/to/workflow.yml"
        assert config.working_directory == "/path/to/work"
        assert config.slurm_options is None
        assert config.matrix_map is None

    def test_from_dict_with_slurm_options(self) -> None:
        """Test creating config with slurm options."""
        config_data = {
            "slurm-ci": {
                "workflow_file": "/path/to/workflow.yml",
                "working_directory": "/path/to/work",
                "slurm": {
                    "partition": "gpu",
                    "time": "02:00:00",
                    "cpus-per-task": 16,
                },
            }
        }

        config = SlurmRunConfig.from_dict(config_data)

        assert config.slurm_options is not None
        assert config.slurm_options["partition"] == "gpu"
        assert config.slurm_options["time"] == "02:00:00"
        assert config.slurm_options["cpus-per-task"] == 16

    def test_from_dict_with_matrix_map(self) -> None:
        """Test creating config with matrix mapping."""
        config_data = {
            "slurm-ci": {
                "workflow_file": "/path/to/workflow.yml",
                "working_directory": "/path/to/work",
                "slurm": {
                    "matrix_map": {
                        "gpu_arch": {
                            "key": "gres",
                            "value_prefix": "gpu:",
                            "value_suffix": "",
                        }
                    }
                },
            }
        }

        config = SlurmRunConfig.from_dict(config_data)

        assert config.matrix_map is not None
        assert "gpu_arch" in config.matrix_map
        assert config.matrix_map["gpu_arch"]["key"] == "gres"

    def test_from_dict_missing_required_fields(self) -> None:
        """Test error handling for missing required fields."""
        config_data = {
            "slurm-ci": {
                "workflow_file": "/path/to/workflow.yml",
                # Missing working_directory
            }
        }

        with pytest.raises(ValueError, match="Missing required configuration fields"):
            SlurmRunConfig.from_dict(config_data)

    def test_from_file(self, tmp_path: Path) -> None:
        """Test loading config from TOML file."""
        config_content = {
            "slurm-ci": {
                "workflow_file": "workflows/ci.yml",
                "working_directory": ".",
                "slurm": {"partition": "gpu", "time": "01:00:00"},
            }
        }

        config_file = tmp_path / "config.toml"
        with open(config_file, "w") as f:
            toml.dump(config_content, f)

        config = SlurmRunConfig.from_file(str(config_file))

        # Paths should be resolved to absolute
        assert Path(config.workflow_file).is_absolute()
        assert Path(config.working_directory).is_absolute()
        assert config.slurm_options["partition"] == "gpu"

    def test_from_file_not_found(self, tmp_path: Path) -> None:
        """Test error handling for non-existent file."""
        missing_file = tmp_path / "missing-config.toml"
        with pytest.raises(FileNotFoundError):
            SlurmRunConfig.from_file(str(missing_file))


class TestApplyMatrixMappings:
    """Tests for apply_matrix_mappings function."""

    def test_basic_mapping(self) -> None:
        """Test basic matrix mapping."""
        sbatch_options = {"job-name": "test", "time": "01:00:00"}
        matrix_combo = {"gpu_arch": "gfx942"}
        matrix_map = {
            "gpu_arch": {"key": "gres", "value_prefix": "gpu:", "value_suffix": ""}
        }

        result = apply_matrix_mappings(sbatch_options, matrix_combo, matrix_map)

        assert result["gres"] == "gpu:gfx942"
        assert result["job-name"] == "test"
        assert result["time"] == "01:00:00"

    def test_mapping_with_prefix_and_suffix(self) -> None:
        """Test mapping with both prefix and suffix."""
        sbatch_options = {}
        matrix_combo = {"version": "3.9"}
        matrix_map = {
            "version": {
                "key": "partition",
                "value_prefix": "python-",
                "value_suffix": "-env",
            }
        }

        result = apply_matrix_mappings(sbatch_options, matrix_combo, matrix_map)

        assert result["partition"] == "python-3.9-env"

    def test_no_mapping(self) -> None:
        """Test when no matrix_map is provided."""
        sbatch_options = {"job-name": "test"}
        matrix_combo = {"key": "value"}

        result = apply_matrix_mappings(sbatch_options, matrix_combo, None)

        assert result == sbatch_options

    def test_mapping_non_existent_matrix_var(self) -> None:
        """Test mapping when matrix var doesn't exist in combo."""
        sbatch_options = {"job-name": "test"}
        matrix_combo = {"os": "ubuntu"}
        matrix_map = {
            "gpu_arch": {"key": "gres", "value_prefix": "gpu:", "value_suffix": ""}
        }

        result = apply_matrix_mappings(sbatch_options, matrix_combo, matrix_map)

        # Should not add gres since gpu_arch is not in matrix_combo
        assert "gres" not in result
        assert result["job-name"] == "test"

    def test_multiple_mappings(self) -> None:
        """Test multiple matrix mappings at once."""
        sbatch_options = {"time": "01:00:00"}
        matrix_combo = {"gpu_arch": "gfx942", "python_version": "3.10"}
        matrix_map = {
            "gpu_arch": {"key": "gres", "value_prefix": "gpu:", "value_suffix": ""},
            "python_version": {
                "key": "partition",
                "value_prefix": "python",
                "value_suffix": "",
            },
        }

        result = apply_matrix_mappings(sbatch_options, matrix_combo, matrix_map)

        assert result["gres"] == "gpu:gfx942"
        assert result["partition"] == "python3.10"
        assert result["time"] == "01:00:00"

    def test_mapping_overwrites_existing(self) -> None:
        """Test that mapping can overwrite existing sbatch options."""
        sbatch_options = {"gres": "gpu:default", "time": "01:00:00"}
        matrix_combo = {"gpu_arch": "gfx942"}
        matrix_map = {
            "gpu_arch": {"key": "gres", "value_prefix": "gpu:", "value_suffix": ""}
        }

        result = apply_matrix_mappings(sbatch_options, matrix_combo, matrix_map)

        assert result["gres"] == "gpu:gfx942"  # Should be overwritten


class TestCreateExampleConfig:
    """Tests for create_example_config function."""

    def test_create_example_config(self, tmp_path: Path) -> None:
        """Test creating example configuration file."""
        output_path = tmp_path / "example-config.toml"

        create_example_config(str(output_path))

        # Verify file was created
        assert output_path.exists()

        # Load and verify content
        with open(output_path, "r") as f:
            config_data = toml.load(f)

        assert "slurm-ci" in config_data
        assert "workflow_file" in config_data["slurm-ci"]
        assert "working_directory" in config_data["slurm-ci"]
        assert "slurm" in config_data["slurm-ci"]
        assert "matrix_map" in config_data["slurm-ci"]["slurm"]
