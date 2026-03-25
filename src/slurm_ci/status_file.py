import hashlib
import logging
import os
import subprocess
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

import toml

from slurm_ci import __version__ as slurm_ci_version
from slurm_ci.config import STATUS_DIR


# TODO add utils to get git hash, project name, git branch, and add them to file
# TODO add link to log tracking


class StatusFile:
    def __init__(
        self,
        workflow_file: str,
        working_directory: str,
        matrix_args: Dict[str, Any],
        git_repo_url: Optional[str] = None,
        git_repo_branch: Optional[str] = None,
    ) -> None:
        self.git_repo_url = git_repo_url
        self.git_repo_branch = git_repo_branch
        self.working_directory = os.path.abspath(working_directory)
        self.logger = logging.getLogger(__name__)

        # Log initialization details
        self.logger.info(f"Creating StatusFile for workflow: {workflow_file}")
        self.logger.info(f"Working directory: {working_directory}")
        if git_repo_url:
            self.logger.info(f"Git-watch mode - Repository URL: {git_repo_url}")
            self.logger.info(f"Git-watch mode - Branch: {git_repo_branch}")
        else:
            self.logger.info("Regular mode - will use local git commands")

        self.data: Dict[str, Any] = OrderedDict(
            {
                # Project/workflow info
                "project": {
                    "name": self.get_project_name(),
                    "workflow_file": workflow_file,
                    "working_directory": self.working_directory,
                },
                # Git info
                "git": {
                    "commit": self.get_git_hash(),
                    "branch": self.git_repo_branch or self.get_git_branch(),
                },
                # General info
                "ci": {
                    # "logfile_path": self.get_logfile_path(),
                    "slurm-ci_version": slurm_ci_version,
                },
                # Slurm info
                "slurm": {
                    # Will be set to slurm job ID or -1 for local runs
                    "job_id": None,
                    # Job state from sacct (e.g., RUNNING, COMPLETED)
                    "state": None,
                    "sacct_exit_code": None,  # Exit code from sacct
                },
                # Matrix configuration (top-level to control section ordering)
                "matrix": matrix_args,
                # Runtime info - MUST BE LAST for bash appends to work
                "runtime": {
                    "start_time": time.time(),
                },
            }
        )

        self.hashed_filename = hashlib.sha256(f"{self.data}".encode()).hexdigest()
        self.status_file = os.path.join(STATUS_DIR, f"{self.hashed_filename}.toml")

        self.logger.debug(f"Generated status file path: {self.status_file}")
        self.logger.debug(f"Generated hash: {self.hashed_filename}")

        # Add logfile path now that we have the hashed filename
        self.data["ci"]["logfile_path"] = self.get_logfile_path()
        self.logger.info("Status file initialized successfully")

    @staticmethod
    def from_file(status_file: str) -> "StatusFile":
        """Create a StatusFile object from a file."""
        logger = logging.getLogger(__name__)
        logger.info(f"Loading StatusFile from: {status_file}")

        try:
            with open(status_file, "r") as f:
                data = toml.load(f)

            logger.debug("Successfully loaded status file data")
            logger.debug(f"Project: {data.get('project', {}).get('name', 'unknown')}")
            logger.debug(
                f"Git commit: {data.get('git', {}).get('commit', 'unknown')[:8]}..."
            )

            sf = StatusFile(
                data["project"]["workflow_file"],
                data["project"]["working_directory"],
                data["matrix"],
            )
            sf.data = data
            sf.status_file = status_file

            logger.info("StatusFile object created from file successfully")
            return sf
        except Exception as e:
            logger.error(f"Failed to load StatusFile from {status_file}: {e}")
            raise

    def read(self) -> Dict[str, Any]:
        with open(self.status_file, "r") as f:
            return toml.load(f)

    def write(self) -> None:
        self.logger.info(f"Writing status file to: {self.status_file}")
        try:
            os.makedirs(STATUS_DIR, exist_ok=True)
            self.logger.debug(f"Ensured status directory exists: {STATUS_DIR}")

            with open(self.status_file, "w") as f:
                toml.dump(self.data, f)

            self.logger.info(f"Successfully wrote status file: {self.status_file}")
            self.logger.debug(
                f"Status file size: {os.path.getsize(self.status_file)} bytes"
            )
        except Exception as e:
            self.logger.error(f"Failed to write status file {self.status_file}: {e}")
            raise

    def get_git_hash(self) -> str:
        if self.git_repo_url:
            self.logger.debug(
                f"Getting git hash from remote repository: {self.git_repo_url}"
            )
            try:
                result = (
                    subprocess.check_output(
                        ["git", "ls-remote", self.git_repo_url, "HEAD"]
                    )
                    .decode("utf-8")
                    .strip()
                    .split("\t")[0]
                )
                self.logger.info(f"Retrieved remote git hash: {result[:8]}...")
                return result
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to get remote git hash: {e}")
                raise
        else:
            self.logger.debug("Getting git hash from local repository")
            try:
                result = (
                    subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=self.working_directory
                    )
                    .decode("utf-8")
                    .strip()
                )
                self.logger.info(f"Retrieved local git hash: {result[:8]}...")
                return result
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to get local git hash: {e}")
                raise

    def get_project_name(self) -> str:
        if self.git_repo_url:
            self.logger.debug(f"Extracting project name from URL: {self.git_repo_url}")
            project_name = self.git_repo_url.split("/")[-1].replace(".git", "")
            self.logger.info(f"Extracted project name: {project_name}")
            return project_name
        else:
            self.logger.debug("Getting project name from local repository")
            try:
                result = os.path.basename(
                    subprocess.check_output(
                        ["git", "rev-parse", "--show-toplevel"],
                        cwd=self.working_directory,
                    )
                    .decode("utf-8")
                    .strip()
                )
                self.logger.info(f"Retrieved local project name: {result}")
                return result
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to get local project name: {e}")
                raise

    def get_git_branch(self) -> str:
        self.logger.debug("Getting git branch from local repository")
        try:
            result = (
                subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=self.working_directory,
                )
                .decode("utf-8")
                .strip()
            )
            self.logger.info(f"Retrieved git branch: {result}")
            return result
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get git branch: {e}")
            raise

    def get_logfile_path(self) -> str:
        logfile_path = os.path.join(STATUS_DIR, f"{self.hashed_filename}.log")
        self.logger.debug(f"Generated logfile path: {logfile_path}")
        return logfile_path

    def set_slurm_job_id(self, job_id: int) -> None:
        """Set the slurm job ID in the status file.

        Args:
            job_id: The slurm job ID (use -1 for local runs)
        """
        self.logger.info(f"Setting slurm job ID to: {job_id}")
        self.data["slurm"]["job_id"] = job_id
        self.write()
