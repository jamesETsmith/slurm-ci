"""Utilities for interacting with SLURM."""

import logging
import subprocess
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)


@dataclass
class SacctResult:
    """Typed result from a sacct query."""

    state: str
    exit_code: Optional[int]


class SacctError(Exception):
    """Raised when sacct is unavailable or returns unusable output."""


def get_job_info_from_sacct(job_id: int) -> Optional[SacctResult]:
    """Query sacct for job information.

    Args:
        job_id: The SLURM job ID.

    Returns:
        :class:`SacctResult` on success, or ``None`` if the job ID is
        invalid / not yet visible to sacct (not an error condition).

    Raises:
        SacctError: If sacct itself is unavailable or returns an
            unexpected format.  Callers that only care about *job* state
            rather than *tool* availability should catch this and treat
            it as "unknown".
    """
    if job_id is None or job_id < 0:
        logger.debug(
            "Skipping sacct query for job_id=%s (local run or not set)", job_id
        )
        return None

    try:
        result = subprocess.run(
            [
                "sacct",
                "-j",
                str(job_id),
                "--format=State,ExitCode",
                "--noheader",
                "--parsable2",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise SacctError(f"sacct query timed out for job {job_id}")
    except FileNotFoundError:
        raise SacctError("sacct binary not found — is Slurm installed?")
    except OSError as e:
        raise SacctError(f"sacct invocation failed for job {job_id}: {e}")

    if result.returncode != 0:
        raise SacctError(
            f"sacct exited {result.returncode} for job {job_id}: "
            f"{result.stderr.strip()}"
        )

    lines = result.stdout.strip().split("\n")
    if not lines or not lines[0]:
        # Job not yet visible to sacct (submitted but not started) — not an error.
        logger.debug("No sacct output for job %s (may not be visible yet)", job_id)
        return None

    # First non-empty line is the main job (not a step).
    parts = lines[0].split("|")
    if len(parts) < 2:
        raise SacctError(
            f"Unexpected sacct output format for job {job_id}: {lines[0]!r}"
        )

    state = parts[0].strip()
    exit_code_str = parts[1].strip()

    exit_code: Optional[int] = None
    if exit_code_str:
        try:
            exit_code = int(exit_code_str.split(":")[0])
        except (ValueError, IndexError):
            logger.warning(
                "Could not parse exit code %r for job %s", exit_code_str, job_id
            )

    logger.debug("Job %s — State: %s, Exit Code: %s", job_id, state, exit_code)
    return SacctResult(state=state, exit_code=exit_code)


_ACTIVE_SLURM_STATES = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED"}


def is_slurm_job_active(job_id: int) -> Optional[bool]:
    """Check whether a Slurm job is still active (queued/running).

    Returns:
        True  — job is active (queued/running).
        False — job has reached a terminal state or is unknown to sacct.
        None  — sacct is unavailable; caller should treat as "unknown".
    """
    try:
        info = get_job_info_from_sacct(job_id)
    except SacctError as e:
        logger.warning("sacct unavailable for job %s: %s", job_id, e)
        return None
    if info is None:
        return None
    return info.state in _ACTIVE_SLURM_STATES
