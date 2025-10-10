import hashlib
import os
import subprocess
import time
from collections import OrderedDict

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
        matrix_args: dict,
    ) -> None:
        self.data = OrderedDict(
            {
                # Project/workflow info
                "project": {
                    "name": self.get_project_name(),
                    "workflow_file": workflow_file,
                    "working_directory": working_directory,
                },
                # Git info
                "git": {
                    "commit": self.get_git_hash(),
                    "branch": self.get_git_branch(),
                },
                # General info
                "ci": {
                    # "logfile_path": self.get_logfile_path(),
                    "slurm-ci_version": slurm_ci_version,
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
        # Add logfile path now that we have the hashed filename
        self.data["ci"]["logfile_path"] = self.get_logfile_path()

    @staticmethod
    def from_file(status_file: str):
        """Create a StatusFile object from a file."""
        with open(status_file, "r") as f:
            data = toml.load(f)
        sf = StatusFile(
            data["project"]["workflow_file"],
            data["project"]["working_directory"],
            data["matrix"],
        )
        sf.data = data
        sf.status_file = status_file
        return sf

    def read(self):
        with open(self.status_file, "r") as f:
            return toml.load(f)

    def write(self) -> None:
        os.makedirs(STATUS_DIR, exist_ok=True)
        with open(self.status_file, "w") as f:
            toml.dump(self.data, f)

    def get_git_hash(self):
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"])
            .decode("utf-8")
            .strip()
        )

    def get_project_name(self):
        return os.path.basename(
            subprocess.check_output(["git", "rev-parse", "--show-toplevel"])
            .decode("utf-8")
            .strip()
        )

    def get_git_branch(self):
        return (
            subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
            .decode("utf-8")
            .strip()
        )

    def get_logfile_path(self):
        return os.path.join(STATUS_DIR, f"{self.hashed_filename}.log")
