import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, Template

import slurm_ci
from slurm_ci.config import STATUS_DIR
from slurm_ci.slurm_run_config import apply_matrix_mappings
from slurm_ci.status_file import StatusFile
from slurm_ci.workflow_parser import WorkflowParser


# Default Jinja2 template for SLURM jobs
DEFAULT_SLURM_TEMPLATE = """#!/bin/bash
{%- for key, value in sbatch_options.items() %}
#SBATCH --{{ key }}={{ value }}
{%- endfor %}

{%- if env_vars %}
# Environment variables
{%- for key, value in env_vars.items() %}
export {{ key }}="{{ value }}"
{%- endfor %}

{%- endif %}
{%- if pre_commands %}
# Pre-execution commands
{%- for command in pre_commands %}
{{ command }}
{%- endfor %}

{%- endif %}
{%- if git_repo %}
# Clone repository on compute node
echo "Cloning repository: {{ git_repo.url }}"
TEMP_REPO_DIR=$(mktemp -d -t slurm-ci-repo-XXXXXX)
git clone --depth 1 --branch {{ git_repo.branch }} {{ git_repo.url }} "$TEMP_REPO_DIR"
cd "$TEMP_REPO_DIR"
git checkout {{ git_repo.commit_sha }}
echo "Repository cloned to: $TEMP_REPO_DIR"

{%- else %}
# Change to the working directory
cd {{ workdir }}

{%- endif %}
# Run the main command
{{ main_command }}
EXIT_CODE=$?

{%- if status_file %}
# Update the status directory with the job result
echo "" >> {{ status_file }}
echo "[runtime.end]" >> {{ status_file }}
echo "time = $(date +%s)" >> {{ status_file }}
echo "exit_code = $EXIT_CODE" >> {{ status_file }}

{%- endif %}
{%- if cleanup_temp_dir %}
{%- if git_repo %}
# Clean up temporary repository directory
if [[ -n "$TEMP_REPO_DIR" && "$TEMP_REPO_DIR" == /tmp/slurm-ci-repo-* ]]; then
    echo "Cleaning up temporary repository directory: $TEMP_REPO_DIR"
    rm -rf "$TEMP_REPO_DIR"
fi
{%- else %}
# Clean up temporary directory if it looks like a slurm-ci temp dir
if [[ "{{ workdir }}" == /tmp/slurm-ci-* ]]; then
    echo "Cleaning up temporary directory: {{ workdir }}"
    rm -rf "{{ workdir }}"
fi
{%- endif %}

{%- endif %}
{%- if post_commands %}
# Post-execution commands
{%- for command in post_commands %}
{{ command }}
{%- endfor %}

{%- endif %}
# Exit with the same code as the main command
exit $EXIT_CODE
"""


class SlurmTemplateRenderer:
    """Handles SLURM job script generation using Jinja2 templates."""

    def __init__(
        self, template_dir: Optional[Path] = None, template_path: Optional[Path] = None
    ) -> None:
        """Initialize the template renderer.

        Args:
            template_dir: Optional directory containing custom templates.
                         If None, uses built-in templates.
            template_path: Optional path to a specific template file.
        """
        self.template_dir = template_dir
        self.template_path = template_path
        self.env = None

        if template_dir and template_dir.exists():
            # Use file-based templates
            self.env = Environment(loader=FileSystemLoader(str(template_dir)))

    def get_template(self, template_name: str = "default") -> Template:
        """Get a template by name.

        Args:
            template_name: Name of the template to load

        Returns:
            Jinja2 Template object
        """
        # If a specific template file path is provided, use it
        if self.template_path and self.template_path.exists():
            try:
                with open(self.template_path, "r") as f:
                    template_content = f.read()
                return Template(template_content)
            except Exception:
                # Fall back to default if custom template fails
                pass

        # If template directory is provided, try to load from it
        if self.env:
            try:
                return self.env.get_template(f"{template_name}.j2")
            except Exception:
                # Fall back to default if custom template fails
                pass

        # Use built-in default template
        return Template(DEFAULT_SLURM_TEMPLATE)

    def render_script(
        self,
        template_name: str = "default",
        workdir: str = "",
        main_command: str = "",
        sbatch_options: Optional[Dict[str, Any]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        pre_commands: Optional[list] = None,
        post_commands: Optional[list] = None,
        status_file: Optional[str] = None,
        cleanup_temp_dir: bool = True,
        git_repo: Optional[Dict[str, str]] = None,
        **kwargs: object,
    ) -> str:
        """Render a SLURM job script from template.

        Args:
            template_name: Name of template to use
            workdir: Working directory for the job
            main_command: Main command to execute
            sbatch_options: Dictionary of SBATCH options
            env_vars: Environment variables to set
            pre_commands: Commands to run before main command
            post_commands: Commands to run after main command
            status_file: Path to status file for job tracking
            cleanup_temp_dir: Whether to clean up temp directories
            git_repo: Git repository info (url, branch, commit_sha)
                for cloning on compute node
            **kwargs: Additional template variables

        Returns:
            Rendered SLURM script as string
        """
        template = self.get_template(template_name)

        context = {
            "workdir": workdir,
            "main_command": main_command,
            "sbatch_options": sbatch_options or {},
            "env_vars": env_vars or {},
            "pre_commands": pre_commands or [],
            "post_commands": post_commands or [],
            "status_file": status_file,
            "cleanup_temp_dir": cleanup_temp_dir,
            "git_repo": git_repo,
            **kwargs,
        }

        return template.render(**context)


def get_default_sbatch_options(
    combo: Dict[str, Any], task_name: str, logfile_path: str
) -> Dict[str, Any]:
    """Get default SBATCH options for a job.

    Args:
        combo: Matrix combination for the job
        task_name: Name for the SLURM job
        logfile_path: Path for job output logs

    Returns:
        Dictionary of SBATCH options
    """

    return {
        "job-name": task_name,
        "output": logfile_path,
        "time": "24:00:00",
        "cpus-per-task": 32,
        # TODO this is just because of the cluster I'm working on
        "gres": "gpu:gfx90a-mi210x",
    }


def build_act_command(
    workflow_file: str, combo: Dict[str, Any], dryrun: bool = False
) -> str:
    """Build the act command with proper arguments.

    Args:
        workflow_file: Path to the specific workflow file to run
        combo: Matrix combination for the job
        dryrun: Whether this is a dry run

    Returns:
        Complete act command string
    """
    act_args = f"--workflows {workflow_file} "
    act_args += " --rm "  # remove the container if the job fails

    for var, value in combo.items():
        act_args += f"--matrix {var}:{value} "

    if dryrun:
        act_args += " --dryrun"

    return f"{slurm_ci.config.ACT_BINARY} {act_args}"


def _launch_single_job(
    status_file: StatusFile,
    dryrun: bool = False,
    template_name: str = "default",
    template_dir: Optional[Path] = None,
    template_path: Optional[Path] = None,
    custom_sbatch_options: Optional[Dict[str, Any]] = None,
    matrix_map: Optional[Dict[str, Dict[str, str]]] = None,
    git_repo: Optional[Dict[str, str]] = None,
) -> None:
    """Helper function to launch a single slurm job.

    Args:
        status_file: Status file for job tracking
        dryrun: Whether this is a dry run
        template_name: Name of template to use
        template_dir: Directory containing custom templates
        template_path: Path to a specific template file
        custom_sbatch_options: Additional SBATCH options to override defaults
        matrix_map: Matrix mapping configuration for dynamic SLURM options
        git_repo: Git repository info (url, branch, commit_sha) for cloning
            on compute node
    """
    combo = status_file.data["matrix"]
    working_directory = status_file.data["project"]["working_directory"]
    workflow_file = status_file.data["project"]["workflow_file"]

    task_name = "_".join([str(value) for value in combo.values()])
    print(str(combo))

    # Initialize template renderer
    renderer = SlurmTemplateRenderer(template_dir, template_path)

    # Get default SBATCH options and merge with custom ones
    sbatch_options = get_default_sbatch_options(
        combo, task_name, status_file.get_logfile_path()
    )
    if custom_sbatch_options:
        sbatch_options.update(custom_sbatch_options)
    # Apply matrix mappings to SLURM options
    sbatch_options = apply_matrix_mappings(sbatch_options, combo, matrix_map)

    print("Writing logfile to: ", status_file.get_logfile_path())

    # Build the main command
    main_command = build_act_command(workflow_file, combo, dryrun)

    # Render the SLURM script
    slurm_script = renderer.render_script(
        template_name=template_name,
        workdir=working_directory,
        main_command=main_command,
        sbatch_options=sbatch_options,
        status_file=status_file.status_file,
        cleanup_temp_dir=True,
        git_repo=git_repo,
    )

    # Add slurm script to status file
    if "slurm" not in status_file.data:
        status_file.data["slurm"] = {}
    status_file.data["slurm"]["slurm_script"] = slurm_script
    status_file.write()

    # Write and submit the script
    slurm_script_path = f"/tmp/sbatch_{task_name}.sh"
    with open(slurm_script_path, "w") as f:
        f.write(slurm_script)

    # Submit the job and capture the job ID
    result = subprocess.run(
        ["sbatch", slurm_script_path], capture_output=True, text=True
    )

    # Parse job ID from sbatch output (format: "Submitted batch job 12345")
    if result.returncode == 0 and result.stdout:
        job_id_str = result.stdout.strip().split()[-1]
        try:
            job_id = int(job_id_str)
            status_file.set_slurm_job_id(job_id)
            print(f"Submitted job {job_id}")
        except ValueError:
            print(
                f"Warning: Could not parse job ID from sbatch output: {result.stdout}"
            )
    else:
        print(f"Error submitting job: {result.stderr}")


def relaunch_slurm_job(
    status_file: StatusFile,
    dryrun: bool = False,
    template_name: str = "default",
    template_dir: Optional[Path] = None,
    template_path: Optional[Path] = None,
    matrix_map: Optional[Dict[str, Dict[str, str]]] = None,
    git_repo: Optional[Dict[str, str]] = None,
) -> None:
    """Relaunches a slurm job from a status file.

    Args:
        status_file: Status file for the job to relaunch
        dryrun: Whether this is a dry run
        template_name: Name of template to use
        template_dir: Directory containing custom templates
        template_path: Path to a specific template file
        matrix_map: Matrix mapping configuration for dynamic SLURM options
        git_repo: Git repository info (url, branch, commit_sha) for cloning
            on compute node
    """
    # Create a new status file for the relaunch to get new log/status file paths
    new_status_file = StatusFile(
        workflow_file=status_file.data["project"]["workflow_file"],
        working_directory=status_file.data["project"]["working_directory"],
        matrix_args=status_file.data["matrix"],
        git_repo_url=status_file.git_repo_url,
        git_repo_branch=status_file.git_repo_branch,
    )
    # Copy over relevant data from the old status file but preserve new paths
    new_status_file.data["git"] = status_file.data["git"].copy()
    new_status_file.data["project"] = status_file.data["project"].copy()

    # Add a relaunch marker to make the hash unique
    new_status_file.data["relaunch"] = {
        "original_status_file": status_file.status_file,
        "relaunch_time": time.time(),
    }

    # Regenerate the hash with the new relaunch data
    import hashlib

    new_status_file.hashed_filename = hashlib.sha256(
        f"{new_status_file.data}".encode()
    ).hexdigest()
    new_status_file.status_file = os.path.join(
        STATUS_DIR, f"{new_status_file.hashed_filename}.toml"
    )

    # Update the logfile path in the data
    new_status_file.data["ci"]["logfile_path"] = new_status_file.get_logfile_path()

    print(f"Relaunching job with new status file: {new_status_file.status_file}")
    print(f"New log file path: {new_status_file.get_logfile_path()}")
    _launch_single_job(
        new_status_file,
        dryrun,
        template_name,
        template_dir,
        template_path,
        None,
        matrix_map,
        git_repo,
    )


def launch_slurm_jobs(
    workflow_file: str,
    working_directory: str,
    dryrun: bool = False,
    template_name: str = "default",
    template_dir: Optional[Path] = None,
    template_path: Optional[Path] = None,
    custom_sbatch_options: Optional[Dict[str, Any]] = None,
    matrix_map: Optional[Dict[str, Dict[str, str]]] = None,
    git_repo: Optional[Dict[str, str]] = None,
    git_repo_url: Optional[str] = None,
    git_repo_branch: Optional[str] = None,
) -> None:
    """Launch SLURM jobs for a workflow.

    Args:
        workflow_file: Path to the workflow file
        working_directory: Working directory for the jobs
        dryrun: Whether this is a dry run
        template_name: Name of template to use
        template_dir: Directory containing custom templates
        template_path: Path to a specific template file
        custom_sbatch_options: Additional SBATCH options to override defaults
        matrix_map: Matrix mapping configuration for dynamic SLURM options
        git_repo: Git repository info (url, branch, commit_sha) for cloning
            on compute node
        git_repo_url: Git repository URL for status file (git-watch only)
        git_repo_branch: Git repository branch for status file (git-watch only)
    """
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
            git_repo_url=git_repo_url,
            git_repo_branch=git_repo_branch,
        )
        status_file.write()
        _launch_single_job(
            status_file,
            dryrun,
            template_name,
            template_dir,
            template_path,
            custom_sbatch_options,
            matrix_map,
            git_repo,
        )
