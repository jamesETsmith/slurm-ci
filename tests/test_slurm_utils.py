"""Tests for slurm_utils.py module."""

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from slurm_ci.slurm_utils import SacctError, SacctResult, get_job_info_from_sacct


def test_get_job_info_from_sacct_skips_invalid_job_ids() -> None:
    assert get_job_info_from_sacct(-1) is None
    assert get_job_info_from_sacct(None) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("COMPLETED|0:0\n", SacctResult(state="COMPLETED", exit_code=0)),
        ("FAILED|1:0\n", SacctResult(state="FAILED", exit_code=1)),
        ("RUNNING|0:15\n", SacctResult(state="RUNNING", exit_code=0)),
        ("COMPLETED|not-an-int\n", SacctResult(state="COMPLETED", exit_code=None)),
    ],
)
def test_get_job_info_from_sacct_parses_output(
    stdout: str, expected: SacctResult
) -> None:
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        assert get_job_info_from_sacct(123) == expected


def test_get_job_info_from_sacct_returns_none_for_empty_output() -> None:
    """Empty output means the job isn't visible yet — not an error."""
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        assert get_job_info_from_sacct(123) is None


def test_get_job_info_from_sacct_raises_on_bad_format() -> None:
    """Malformed sacct output is a tool error, not a missing-job signal."""
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout="BADLINE", stderr=""
        )
        with pytest.raises(SacctError, match="Unexpected sacct output format"):
            get_job_info_from_sacct(123)


def test_get_job_info_from_sacct_raises_on_nonzero_exit() -> None:
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with pytest.raises(SacctError, match="sacct exited 1"):
            get_job_info_from_sacct(123)


def test_get_job_info_from_sacct_raises_on_timeout() -> None:
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sacct", timeout=10)
        with pytest.raises(SacctError, match="timed out"):
            get_job_info_from_sacct(123)


def test_get_job_info_from_sacct_raises_on_unexpected_error() -> None:
    with patch("slurm_ci.slurm_utils.subprocess.run") as mock_run:
        mock_run.side_effect = OSError("disk error")
        with pytest.raises(SacctError):
            get_job_info_from_sacct(123)
