import json
from typing import Dict


class SlurmJobRunner:
    def __init__(self, slurm_config) -> None:
        self.config = slurm_config

    def run_job(self, job_spec: Dict, matrix_vars: Dict) -> None:
        sbatch_script = self._generate_sbatch_script(job_spec, matrix_vars)

        # Submit the job to Slurm
        # subprocess.run(["sbatch"], input=sbatch_script, text=True)

        print("--- SBATCH SCRIPT ---")
        print(sbatch_script)
        print("---------------------")

    def _generate_sbatch_script(self, job_spec: Dict, matrix_vars: Dict) -> str:
        job_name = job_spec.get("name", "slurm-ci-job")
        gpu_arch = matrix_vars.get("gpu_arch")
        constraint = f"#SBATCH --constraint={gpu_arch}" if gpu_arch else ""

        job_spec_json = json.dumps(job_spec)
        matrix_vars_json = json.dumps(matrix_vars)

        executor_path = self.config.EXECUTOR_PATH

        sbatch_script = f"""#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --output={job_name}-%j.out
#SBATCH --error={job_name}-%j.err
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:1
{constraint}

set -e
set -x

# It's important that the python environment on the node can run the executor
python3 {executor_path} '{job_spec_json}' '{matrix_vars_json}'
"""
        return sbatch_script
