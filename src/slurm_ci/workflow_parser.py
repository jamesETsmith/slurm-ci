import itertools

import yaml


class WorkflowParser:
    def __init__(self, workflow_content) -> None:
        self.workflow = yaml.safe_load(workflow_content)

    def get_jobs(self):
        return self.workflow.get("jobs", {})

    def get_job_matrix(self, job_name):
        job = self.get_jobs().get(job_name, {})
        return job.get("strategy", {}).get("matrix", {})

    def generate_matrix_combinations(self):
        combinations = []
        for job_name, job in self.get_jobs().items():
            matrix = self.get_job_matrix(job_name)
            if not matrix:
                continue

            keys = matrix.keys()
            values = [matrix[key] for key in keys]

            for combo_values in itertools.product(*values):
                combinations.append(dict(zip(keys, combo_values)))

        return combinations
