import os
from pathlib import Path


def _make_dir(path: Path) -> Path:
    """Create a directory and verify it is writable. Raises on failure."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"slurm-ci could not create required directory {path}: {e}"
        ) from e
    if not os.access(path, os.W_OK):
        raise RuntimeError(
            f"slurm-ci directory {path} exists but is not writable. "
            "Check permissions or override with the appropriate env var."
        )
    return path


# Base slurm-ci directory
SLURM_CI_DIR = _make_dir(
    Path(os.environ.get("SLURM_CI_DIR", Path.home() / ".slurm-ci"))
)

DATABASE_URL = f"sqlite:///{SLURM_CI_DIR}/slurm_ci.db"

STATUS_DIR = str(
    _make_dir(
        Path(os.environ.get("SLURM_CI_STATUS_DIR", str(SLURM_CI_DIR / "job_status")))
    )
)

ACT_PATH = str(_make_dir(SLURM_CI_DIR / "bin"))
ACT_BINARY = os.environ.get(
    "SLURM_CI_ACT_BINARY",
    str(Path(ACT_PATH) / "act"),
)

# Git-watch directories
GIT_WATCH_DIR = str(_make_dir(SLURM_CI_DIR / "git-watch"))
git_watch_path = Path(GIT_WATCH_DIR)
_make_dir(git_watch_path / "pids")
_make_dir(git_watch_path / "status")
_make_dir(git_watch_path / "logs")
