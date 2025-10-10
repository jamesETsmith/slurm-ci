import os
import time

import pytest

from slurm_ci.slurm_launcher import relaunch_slurm_job
from slurm_ci.status_file import StatusFile


cwd = os.path.dirname(os.path.abspath(__file__))
project_dir = f"{cwd}/../sample_project"
workflow_file = f"{project_dir}/.slurm-ci/workflows/ci.yml"


@pytest.fixture
def status_file(tmpdir):
    """Create a status file in a temporary directory."""
    sf = StatusFile(
        workflow_file=workflow_file,
        working_directory=project_dir,
        matrix_args={"python-version": "3.9", "os": "ubuntu-latest"},
    )
    sf.status_file = os.path.join(str(tmpdir), "status.toml")
    sf.write()
    return sf


def test_relaunch(status_file) -> None:
    """Test relaunching a job from a status file."""
    # Relaunch the job
    relaunch_slurm_job(status_file, dryrun=False)

    # Wait for the job to complete
    timeout = 60  # seconds
    start_time = time.time()
    restarted = False
    while time.time() - start_time < timeout:
        sf_data = status_file.read()
        if "end" in sf_data.get("runtime", {}):
            restarted = True
            break
        time.sleep(1)

    assert restarted, "Job did not complete within the timeout period."
    assert "end" in status_file.read()["runtime"]
