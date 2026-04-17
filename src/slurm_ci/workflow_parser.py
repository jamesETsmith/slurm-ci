import itertools
from typing import Any, Dict, List

import yaml


class WorkflowParser:
    """Parser for GitHub Actions workflow files with matrix support.

    This class handles parsing YAML workflow files and generating matrix
    combinations including support for the 'include' directive.
    """

    def __init__(self, workflow_file: str) -> None:
        """Initialize the workflow parser.

        Parameters
        ----------
        workflow_file : str
            Path to the workflow YAML file to parse.
        """
        with open(workflow_file) as f:
            workflow_content = f.read()
        self.workflow = yaml.safe_load(workflow_content)
        self._validate_matrix_job_names()

    def _validate_matrix_job_names(self) -> None:
        """Validate that all matrix jobs have dynamic names.

        Because act derives container names from the job name, matrix jobs
        must include a matrix variable in their name (e.g. ${{ matrix.var }})
        to prevent container name collisions on the same node.

        Raises
        ------
        ValueError
            If a matrix job lacks a dynamic name.
        """
        for job_name, job in self.get_jobs().items():
            if not isinstance(job, dict):
                continue

            matrix = job.get("strategy", {}).get("matrix")
            if not matrix:
                continue

            job_display_name = job.get("name", "")
            has_matrix_var = "${{" in job_display_name and "matrix." in job_display_name
            if not job_display_name or not has_matrix_var:
                raise ValueError(
                    f"Job '{job_name}' uses a matrix but lacks a dynamic name. "
                    "To prevent container collisions, you must provide a 'name:' "
                    "field that includes a matrix variable "
                    f"(e.g., 'name: {job_name} ${{{{ matrix.var }}}}')."
                )

    def get_jobs(self) -> Dict[str, Any]:
        """Get all jobs defined in the workflow.

        Returns
        -------
        Dict[str, Any]
            Dictionary of job names to job configurations.
        """
        return self.workflow.get("jobs", {})

    def get_job_matrix(self, job_name: str) -> Dict[str, Any]:
        """Get the complete matrix configuration for a specific job.

        Parameters
        ----------
        job_name : str
            Name of the job to get matrix for.

        Returns
        -------
        Dict[str, Any]
            The complete matrix configuration including 'include' if present.
        """
        job = self.get_jobs().get(job_name, {})
        return job.get("strategy", {}).get("matrix", {})

    def get_job_matrix_base(self, job_name: str) -> Dict[str, List[Any]]:
        """Get matrix excluding 'include' section for base combinations.

        Parameters
        ----------
        job_name : str
            Name of the job to get base matrix for.

        Returns
        -------
        Dict[str, List[Any]]
            Dictionary of matrix variables to their possible values,
            excluding the 'include' section.
        """
        matrix = self.get_job_matrix(job_name)
        return {k: v for k, v in matrix.items() if k != "include"}

    def get_job_matrix_include(self, job_name: str) -> List[Dict[str, Any]]:
        """Get the 'include' section of the matrix.

        Parameters
        ----------
        job_name : str
            Name of the job to get matrix include for.

        Returns
        -------
        List[Dict[str, Any]]
            List of include objects that specify additional matrix combinations
            or modifications to existing combinations.
        """
        matrix = self.get_job_matrix(job_name)
        return matrix.get("include", [])

    def generate_matrix_combinations(self) -> List[Dict[str, Any]]:
        """Generate all matrix combinations for all jobs in the workflow.

        Returns
        -------
        List[Dict[str, Any]]
            List of all matrix combinations across all jobs. Each combination
            is a dictionary of variable names to their values.
        """
        combinations = []
        for job_name, job in self.get_jobs().items():
            job_combinations = self._generate_job_matrix_combinations(job_name)
            combinations.extend(job_combinations)
        return combinations

    def _generate_job_matrix_combinations(self, job_name: str) -> List[Dict[str, Any]]:
        """Generate matrix combinations for a single job, including include logic.

        Parameters
        ----------
        job_name : str
            Name of the job to generate combinations for.

        Returns
        -------
        List[Dict[str, Any]]
            List of matrix combinations for the specified job. Each combination
            includes both base matrix variables and any additions from includes.
        """
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

    def _apply_matrix_includes(
        self, combinations: List[Dict[str, Any]], include_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Apply matrix include logic to existing combinations.

        This implements GitHub Actions matrix include behavior:
        - If include object matches an existing combination, merge properties
        - If include object doesn't match any combination, create new combination
        - Added matrix values can overwrite existing values
        - Original matrix values cannot be overwritten by includes

        Parameters
        ----------
        combinations : List[Dict[str, Any]]
            List of base matrix combinations.
        include_list : List[Dict[str, Any]]
            List of include objects to apply.

        Returns
        -------
        List[Dict[str, Any]]
            Updated list of combinations with includes applied.
        """
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

    def _include_matches_combination(
        self, include_obj: Dict[str, Any], combination: Dict[str, Any]
    ) -> bool:
        """Check if an include object matches a combination.

        An include matches if all key-value pairs that exist in both
        the include and combination are identical. Keys that exist only
        in the include are ignored for matching purposes.

        Parameters
        ----------
        include_obj : Dict[str, Any]
            The include object to check for matching.
        combination : Dict[str, Any]
            The base combination to match against.

        Returns
        -------
        bool
            True if the include object matches the combination, False otherwise.
        """
        for key, value in include_obj.items():
            if key in combination and combination[key] != value:
                return False
        return True
