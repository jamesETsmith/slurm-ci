"""Tests for slurm_utils.py module."""

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from slurm_ci.slurm_utils import get_job_info_from_sacct


def test_get_job_info_from_sacct_skips_invalid_job_ids() -> None:
    assert get_job_info_from_sacct(-1) is None
    assert get_job_info_from_sacct(None) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("COMPLETED|0:0\n", {"state": "COMPLETED", "exit_code": 0}),
        ("FAILED|1:0\n", {"state": "FAILED", "exit_code": 1}),
        ("RUNNING|0:15\n", {"state": "RUNNING", "exit_code": 0}),
        ("COMPLETED|not-an-int\n", {"state": "COMPLETED", "exit_code": None}),
    ],
)
def test_get_job_info_from_sacct_parses_output(stdout: str, expected: dict) -> None:
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        assert get_job_info_from_sacct(123) == expected


def test_get_job_info_from_sacct_handles_bad_outputs() -> None:
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        assert get_job_info_from_sacct(123) is None

        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout="BADLINE", stderr=""
        )
        assert get_job_info_from_sacct(123) is None

        mock_run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        assert get_job_info_from_sacct(123) is None


def test_get_job_info_from_sacct_handles_exceptions() -> None:
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sacct", timeout=10)
        assert get_job_info_from_sacct(123) is None

        mock_run.side_effect = RuntimeError("unexpected")
        assert get_job_info_from_sacct(123) is None
