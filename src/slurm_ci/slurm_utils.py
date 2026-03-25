"""Utilities for interacting with SLURM."""

import logging
import subprocess
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


def get_job_info_from_sacct(job_id: int) -> Optional[Dict[str, Any]]:
    """Query sacct for job information.

    Args:
        job_id: The SLURM job ID

    Returns:
        Dictionary with 'state' and 'exit_code' keys, or None if query fails
    """
    if job_id is None or job_id < 0:
        logger.debug(f"Skipping sacct query for job_id={job_id} (local run or not set)")
        return None

    try:
        # Query sacct for job state and exit code
        # Format: State|ExitCode
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

        if result.returncode != 0:
            logger.warning(f"sacct query failed for job {job_id}: {result.stderr}")
            return None

        # Parse output - get the first line (main job info, not job steps)
        lines = result.stdout.strip().split("\n")
        if not lines or not lines[0]:
            logger.warning(f"No output from sacct for job {job_id}")
            return None

        # First line is the main job, format: STATE|EXIT_CODE:SIGNAL
        parts = lines[0].split("|")
        if len(parts) < 2:
            logger.warning(
                f"Unexpected sacct output format for job {job_id}: {lines[0]}"
            )
            return None

        state = parts[0].strip()
        exit_code_str = parts[1].strip()

        # Parse exit code (format is "exitcode:signal", we want just the exit code)
        exit_code = None
        if exit_code_str and exit_code_str != "":
            try:
                # Exit code format can be "0:0" or just "0"
                exit_code = int(exit_code_str.split(":")[0])
            except (ValueError, IndexError):
                logger.warning(f"Could not parse exit code from: {exit_code_str}")

        logger.debug(f"Job {job_id} - State: {state}, Exit Code: {exit_code}")

        return {"state": state, "exit_code": exit_code}

    except subprocess.TimeoutExpired:
        logger.error(f"sacct query timed out for job {job_id}")
        return None
    except Exception as e:
        logger.error(f"Error querying sacct for job {job_id}: {e}")
        return None


_ACTIVE_SLURM_STATES = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED"}


def is_slurm_job_active(job_id: int) -> Optional[bool]:
    """Check whether a Slurm job is still active (queued/running).

    Returns True if active, False if terminal/gone, or None if we cannot
    determine (e.g. sacct unavailable).
    """
    info = get_job_info_from_sacct(job_id)
    if info is None:
        return None
    return info.get("state", "") in _ACTIVE_SLURM_STATES
