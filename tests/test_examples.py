"""Tests to ensure examples/ remains runnable and up to date."""

import os
import subprocess
from pathlib import Path

from slurm_ci.git_watch_config import GitWatchConfig


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


def test_example_shell_scripts_are_bash_syntax_valid() -> None:
    scripts = sorted(EXAMPLES_DIR.glob("**/*.sh"))
    assert scripts, "No example shell scripts found"
    for script in scripts:
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_example_shell_scripts_execute_with_mock_slurm_ci(tmp_path: Path) -> None:
    mock_bin_dir = tmp_path / "bin"
    mock_bin_dir.mkdir()
    calls_log = tmp_path / "calls.log"

    mock_slurm_ci = mock_bin_dir / "slurm-ci"
    mock_slurm_ci.write_text(
        f'#!/usr/bin/env bash\nset -euo pipefail\necho "$*" >> "{calls_log}"\n'
    )
    mock_slurm_ci.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{mock_bin_dir}:{env.get('PATH', '')}"

    scripts = sorted(EXAMPLES_DIR.glob("**/*.sh"))
    for script in scripts:
        subprocess.run(["bash", str(script)], env=env, check=True)

    calls = calls_log.read_text().splitlines()
    assert any(call.startswith("local-run ") for call in calls)
    assert any("--workflow_file" in call for call in calls)
    assert any("--working_directory" in call for call in calls)
    assert any("--generate-template" in call for call in calls)
    assert any(call.startswith("slurm-run --config ") for call in calls)


def test_git_watch_example_config_is_loadable_and_valid() -> None:
    config_file = EXAMPLES_DIR / "03_git_watch" / "git-watch-config.toml"
    config = GitWatchConfig.from_file(str(config_file))
    config.validate()

    assert config.daemon_name
    assert config.repo_url.startswith(("https://github.com/", "git@github.com:"))
