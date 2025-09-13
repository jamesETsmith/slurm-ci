from .job_runners.local_docker_runner import LocalContainerRunner
from .workflow_parser import WorkflowParser

from pathlib import Path
from typing import Dict

from .job_runners.slurm_runner import SlurmJobRunner
# from .job_runners.cluster_job_runner import ClusterJobRunner


class LocalOrchestrator:
    def __init__(self, working_directory: str, cluster_config: Dict = None) -> None:
        self.working_dir = Path(working_directory).resolve()
        self.container_runner = LocalContainerRunner()
        self.use_cluster = cluster_config is not None

        if self.use_cluster:
            self.cluster_runner = ClusterJobRunner(cluster_config)

    def execute_local_workflow(
        self,
        workflow_file: str = None,
        matrix_combination: Dict = None,
        execution_mode: str = "local",
    ):
        """Execute workflow from local working directory"""

        # Auto-discover workflow file if not specified
        if not workflow_file:
            workflow_file = self._discover_workflow_file()

        workflow_path = self.working_dir / workflow_file
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {workflow_path}")

        # Parse workflow
        with open(workflow_path, "r") as f:
            workflow_content = f.read()
        parser = WorkflowParser(workflow_content)
        jobs = parser.get_jobs()

        # If no matrix specified, extract from workflow
        if not matrix_combination:
            matrix_combinations = parser.generate_matrix_combinations()
            if not matrix_combinations:
                matrix_combinations = [{}]  # Empty matrix for simple workflows
        else:
            matrix_combinations = [matrix_combination]

        # Execute each matrix combination
        results = []
        for matrix_vars in matrix_combinations:
            if execution_mode == "local":
                result = self._execute_locally(jobs, matrix_vars)
            elif execution_mode == "cluster":
                result = self._execute_on_cluster(jobs, matrix_vars)
            else:
                raise ValueError(f"Unknown execution mode: {execution_mode}")

            results.append(result)

        return results

    def _discover_workflow_file(self) -> str:
        """Auto-discover workflow files in working directory"""
        workflow_paths = [
            ".amd/workflows/ci.yml",
            ".amd/workflows/main.yml",
            ".github/workflows/ci.yml",
            ".github/workflows/main.yml",
        ]

        for path in workflow_paths:
            if (self.working_dir / path).exists():
                return path

        # Look for any .yml files in workflow directories
        for workflow_dir in [".amd/workflows", ".github/workflows"]:
            workflow_dir_path = self.working_dir / workflow_dir
            if workflow_dir_path.exists():
                yml_files = list(workflow_dir_path.glob("*.yml"))
                if yml_files:
                    return str(yml_files[0].relative_to(self.working_dir))

        raise FileNotFoundError("No workflow files found in working directory")
