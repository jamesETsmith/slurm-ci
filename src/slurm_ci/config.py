import os
from pathlib import Path

# Base slurm-ci directory
SLURM_CI_DIR = Path.home() / ".slurm-ci"
SLURM_CI_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{SLURM_CI_DIR}/slurm_ci.db"

STATUS_DIR = os.environ.get(
    "SLURM_CI_STATUS_DIR",
    str(SLURM_CI_DIR / "job_status"),
)
Path(STATUS_DIR).mkdir(exist_ok=True)

ACT_PATH = str(SLURM_CI_DIR / "bin")
Path(ACT_PATH).mkdir(exist_ok=True)
ACT_BINARY = os.environ.get(
    "SLURM_CI_ACT_BINARY",
    str(Path(ACT_PATH) / "act"),
)

# Git-watch directories
GIT_WATCH_DIR = str(SLURM_CI_DIR / "git-watch")
git_watch_path = Path(GIT_WATCH_DIR)
git_watch_path.mkdir(exist_ok=True)
(git_watch_path / "pids").mkdir(exist_ok=True)
(git_watch_path / "status").mkdir(exist_ok=True)
(git_watch_path / "logs").mkdir(exist_ok=True)
(git_watch_path / "repos").mkdir(exist_ok=True)
