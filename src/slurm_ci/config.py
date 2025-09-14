import os

os.makedirs(os.path.expanduser("~") + "/.slurm-ci", exist_ok=True)
DATABASE_URL = f"sqlite:///{os.path.expanduser('~')}/.slurm-ci/slurm_ci.db"

STATUS_DIR = os.environ.get(
    "SLURM_CI_STATUS_DIR",
    os.path.expanduser("~") + "/.slurm-ci/job_status",
)
os.makedirs(STATUS_DIR, exist_ok=True)
