import itertools

import yaml


class WorkflowParser:
    def __init__(self, workflow_file) -> None:
        with open(workflow_file) as f:
            workflow_content = f.read()
        self.workflow = yaml.safe_load(workflow_content)

    def get_jobs(self):
        return self.workflow.get("jobs", {})

    def get_job_matrix(self, job_name):
        job = self.get_jobs().get(job_name, {})
        return job.get("strategy", {}).get("matrix", {})

    def get_job_matrix_base(self, job_name):
        """Get matrix excluding 'include' section for base combinations."""
        matrix = self.get_job_matrix(job_name)
        return {k: v for k, v in matrix.items() if k != "include"}

    def get_job_matrix_include(self, job_name):
        """Get the 'include' section of the matrix."""
        matrix = self.get_job_matrix(job_name)
        return matrix.get("include", [])

    def generate_matrix_combinations(self):
        combinations = []
        for job_name, job in self.get_jobs().items():
            job_combinations = self._generate_job_matrix_combinations(job_name)
            combinations.extend(job_combinations)
        return combinations

    def _generate_job_matrix_combinations(self, job_name):
        """Generate matrix combinations for a single job, including include logic."""
        base_matrix = self.get_job_matrix_base(job_name)
        include_list = self.get_job_matrix_include(job_name)

        # If no base matrix, return empty list
        if not base_matrix:
            return []

        # Generate base combinations
        keys = list(base_matrix.keys())
        values = [base_matrix[key] for key in keys]
        combinations = []

        for combo_values in itertools.product(*values):
            combinations.append(dict(zip(keys, combo_values)))

        # Apply include logic
        combinations = self._apply_matrix_includes(combinations, include_list)

        return combinations

    def _apply_matrix_includes(self, combinations, include_list):
        """Apply matrix include logic to existing combinations."""
        if not include_list:
            return combinations

        result_combinations = combinations.copy()

        for include_obj in include_list:
            matched = False

            # Try to match include_obj with existing combinations
            for i, combo in enumerate(result_combinations):
                if self._include_matches_combination(include_obj, combo):
                    # Add include properties to this combination
                    # Note: added matrix values can be overwritten
                    result_combinations[i] = {**combo, **include_obj}
                    matched = True

            # If include_obj doesn't match any existing combination, create new one
            if not matched:
                result_combinations.append(include_obj.copy())

        return result_combinations

    def _include_matches_combination(self, include_obj, combination):
        """
        Check if an include object matches a combination.
        An include matches if all key-value pairs that exist in both
        the include and combination are identical.
        """
        for key, value in include_obj.items():
            if key in combination and combination[key] != value:
                return False
        return True
