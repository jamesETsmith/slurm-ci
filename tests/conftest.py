import atexit
import os
import tempfile
from pathlib import Path


# Create a temporary directory for the entire test session
_test_dir = tempfile.TemporaryDirectory()

# Set environment variables BEFORE any slurm_ci modules are imported
os.environ["SLURM_CI_DIR"] = _test_dir.name
os.environ["SLURM_CI_STATUS_DIR"] = os.path.join(_test_dir.name, "job_status")

# Preserve the real act binary path if it exists, otherwise it will fail the CLI check
real_act = Path.home() / ".slurm-ci" / "bin" / "act"
if real_act.exists():
    os.environ["SLURM_CI_ACT_BINARY"] = str(real_act)
else:
    # Just touch a fake one so the CLI check passes
    fake_act = Path(_test_dir.name) / "bin" / "act"
    fake_act.parent.mkdir(parents=True, exist_ok=True)
    fake_act.touch()
    fake_act.chmod(0o755)
    os.environ["SLURM_CI_ACT_BINARY"] = str(fake_act)

# Ensure cleanup happens when the test process exits
atexit.register(_test_dir.cleanup)
