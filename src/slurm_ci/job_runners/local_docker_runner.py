import json
import subprocess
import sys
from pathlib import Path
from typing import Dict


class LocalContainerRunner:
    def run_job(self, job_spec: Dict, matrix_vars: Dict) -> Dict:
        """
        Run a job by invoking the job_executor.py script in a subprocess.
        """
        job_spec_json = json.dumps(job_spec)
        matrix_vars_json = json.dumps(matrix_vars)

        # Assuming job_executor is runnable and in the same directory context
        executor_path = Path(__file__).parent.parent / "job_executor.py"

        try:
            process = subprocess.run(
                [
                    "python3",
                    str(executor_path),
                    job_spec_json,
                    matrix_vars_json,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            print(process.stdout)
            return {"success": True, "output": process.stdout}
        except subprocess.CalledProcessError as e:
            print(f"Job execution failed with exit code {e.returncode}")
            print(e.stdout)
            print(e.stderr, file=sys.stderr)
            return {"success": False, "output": e.stdout, "error": e.stderr}
