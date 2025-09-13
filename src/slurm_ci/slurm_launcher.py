import os
import subprocess
from slurm_ci.workflow_parser import WorkflowParser


SLURM_TEMPLATE = """#!/bin/bash
#SBATCH --job-name={TASK_NAME}
#SBATCH --time=24:00:00       # Request 24 hours of wall time
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:{GFX_ARCH}

cd {WORKDIR}

act {ACT_ARGS}

exit 0
"""


def launch_slurm_jobs(workflow_file: str, working_directory: str) -> None:
    # get dir of workflow file
    workflow_dir = os.path.dirname(workflow_file)
    parser = WorkflowParser(workflow_file)

    matrix_combinations = parser.generate_matrix_combinations()
    for combo in matrix_combinations:
        # gpu_arch is special here because it's also used in the gres line of the slurm script
        gfx_arch = combo["gpu_arch"]

        act_args = f"--workflows {workflow_dir} " + "".join(
            [f"--matrix {var}:{value} " for var, value in combo.items()]
        )

        task_name = "_".join([value for value in combo.values()])

        slurm_script = SLURM_TEMPLATE.format(
            TASK_NAME=task_name,
            WORKDIR=working_directory,
            ACT_ARGS=act_args,
            GFX_ARCH=gfx_arch,
        )

        with open(f"sbatch_{task_name}.sh", "w") as f:
            f.write(slurm_script)

        subprocess.run(["sbatch", f"sbatch_{task_name}.sh"])
