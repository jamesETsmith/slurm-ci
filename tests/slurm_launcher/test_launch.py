import os

from slurm_ci.slurm_launcher import launch_slurm_jobs


cwd = os.path.dirname(os.path.abspath(__file__))


def test_launch_slurm_jobs() -> None:
    launch_slurm_jobs(
        f"{cwd}/../sample_project/.slurm-ci/workflows/ci.yml",
        f"{cwd}/../sample_project",
    )
