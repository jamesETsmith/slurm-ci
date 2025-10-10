import os
import subprocess

from slurm_ci.status_file import StatusFile
from slurm_ci.workflow_parser import WorkflowParser

SLURM_TEMPLATE = """#!/bin/bash
#SBATCH --job-name={TASK_NAME}
#SBATCH --output={LOGFILE_PATH}
#SBATCH --time=24:00:00       # Request 24 hours of wall time
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:{GFX_ARCH}

# Change to the working directory
cd {WORKDIR}

# Run the act command
# TODO make this configurable
~/apps/nektos/bin/act {ACT_ARGS}
ACT_EXIT_CODE=$?

# Update the status directory with the job result
echo "" >> {STATUSFILE_PATH}
echo "[runtime.end]" >> {STATUSFILE_PATH}
echo "time = $(date +%s)" >> {STATUSFILE_PATH}
echo "exit_code = $ACT_EXIT_CODE" >> {STATUSFILE_PATH}

# Exit with the same code as act (so we have another way to track the job)
exit $ACT_EXIT_CODE
"""


def _launch_single_job(status_file: StatusFile, dryrun: bool = False) -> None:
    """Helper function to launch a single slurm job."""

    combo = status_file.data["matrix"]
    working_directory = status_file.data["project"]["working_directory"]
    workflow_file = status_file.data["project"]["workflow_file"]
    workflow_dir = os.path.dirname(workflow_file)

    # gpu_arch is special here because it's also used in the gres line of the slurm script
    gfx_arch = combo.get("gpu_arch", "gfx942")

    # Use the workflows directory - act will find all workflow files in it
    act_args = f"--workflows {workflow_dir} "
    act_args += " --rm "  # remove the container after the job is done
    for var, value in combo.items():
        act_args += f"--matrix {var}:{value} "

    if dryrun:
        act_args += " --dryrun"

    task_name = "_".join([str(value) for value in combo.values()])
    print(str(combo))

    # Configure the slurm script
    slurm_script = SLURM_TEMPLATE.format(
        TASK_NAME=task_name,
        WORKDIR=working_directory,
        ACT_ARGS=act_args,
        GFX_ARCH=gfx_arch,
        # Reporting
        STATUSFILE_PATH=status_file.status_file,
        LOGFILE_PATH=status_file.get_logfile_path(),
    )

    slurm_script_path = f"/tmp/sbatch_{task_name}.sh"
    with open(slurm_script_path, "w") as f:
        f.write(slurm_script)

    subprocess.run(["sbatch", slurm_script_path])


def relaunch_slurm_job(status_file: StatusFile, dryrun: bool = False) -> None:
    """Relaunches a slurm job from a status file."""

    # remove old runtime info
    if "end" in status_file.data["runtime"]:
        del status_file.data["runtime"]["end"]
    if "slurm_job_id" in status_file.data["runtime"]:
        del status_file.data["runtime"]["slurm_job_id"]

    status_file.write()
    _launch_single_job(status_file, dryrun)


def launch_slurm_jobs(
    workflow_file: str, working_directory: str, dryrun: bool = False
) -> None:
    # get dir of workflow file
    parser = WorkflowParser(workflow_file)

    # make sure working directory is absolute
    working_directory = os.path.abspath(working_directory)

    matrix_combinations = parser.generate_matrix_combinations()
    for combo in matrix_combinations:
        # Start status file
        status_file = StatusFile(
            workflow_file=workflow_file,
            working_directory=working_directory,
            matrix_args=combo,
        )
        status_file.write()
        _launch_single_job(status_file, dryrun)
