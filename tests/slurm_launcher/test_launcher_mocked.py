"""Tests for slurm_launcher.py with mocked Slurm job submission."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from slurm_ci.slurm_launcher import (
    SlurmTemplateRenderer,
    build_act_command,
    get_default_sbatch_options,
    launch_slurm_jobs,
    relaunch_slurm_job,
)
from slurm_ci.status_file import StatusFile


@pytest.fixture
def sample_workflow_file(tmp_path: Path) -> Path:
    """Create a sample workflow file for testing."""
    workflow_content = """
name: Test Workflow
jobs:
  test:
    name: test ${{ matrix.python-version }}
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10"]
        os: ["ubuntu-latest"]
"""
    workflow_file = tmp_path / "workflow.yml"
    workflow_file.write_text(workflow_content)
    return workflow_file


@pytest.fixture
def working_directory(tmp_path: Path) -> Path:
    """Create a temporary working directory."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    return work_dir


class TestSlurmTemplateRenderer:
    """Tests for SlurmTemplateRenderer class."""

    def test_default_template_rendering(self) -> None:
        """Test rendering with default template."""
        renderer = SlurmTemplateRenderer()

        script = renderer.render_script(
            workdir="/path/to/work",
            main_command="echo 'test'",
            sbatch_options={"job-name": "test-job", "time": "01:00:00"},
            env_vars={"MY_VAR": "value"},
        )

        assert "#!/bin/bash" in script
        assert "#SBATCH --job-name=test-job" in script
        assert "#SBATCH --time=01:00:00" in script
        assert 'export MY_VAR="value"' in script
        assert "cd /path/to/work" in script
        assert "echo 'test'" in script

    def test_custom_template_from_file(self, tmp_path: Path) -> None:
        """Test rendering with custom template file."""
        custom_template = tmp_path / "custom.j2"
        custom_template.write_text(
            "#!/bin/bash\n# Custom template\n{{ main_command }}\n"
        )

        renderer = SlurmTemplateRenderer(template_path=custom_template)
        script = renderer.render_script(main_command="ls -la")

        assert "# Custom template" in script
        assert "ls -la" in script

    def test_template_with_pre_and_post_commands(self) -> None:
        """Test template rendering with pre and post commands."""
        renderer = SlurmTemplateRenderer()

        script = renderer.render_script(
            workdir="/work",
            main_command="python script.py",
            pre_commands=["module load python", "source venv/bin/activate"],
            post_commands=["echo 'Job complete'"],
        )

        assert "module load python" in script
        assert "source venv/bin/activate" in script
        assert "python script.py" in script
        assert "echo 'Job complete'" in script

    def test_template_with_git_repo(self) -> None:
        """Test template rendering with git repository cloning."""
        renderer = SlurmTemplateRenderer()

        git_repo = {
            "url": "https://github.com/user/repo",
            "branch": "main",
            "commit_sha": "abc123",
        }

        script = renderer.render_script(
            workdir="/work",
            main_command="make test",
            git_repo=git_repo,
        )

        assert "git clone" in script
        assert "https://github.com/user/repo" in script
        assert "git checkout abc123" in script

    def test_template_with_status_file(self) -> None:
        """Test template rendering with status file tracking."""
        renderer = SlurmTemplateRenderer()

        script = renderer.render_script(
            workdir="/work",
            main_command="echo test",
            status_file="/path/to/status.toml",
        )

        assert "/path/to/status.toml" in script
        assert "[runtime.end]" in script
        assert "exit_code = $EXIT_CODE" in script

    def test_template_with_embedded_workflow(self) -> None:
        """Test that workflow content is embedded as a heredoc."""
        renderer = SlurmTemplateRenderer()
        workflow_yaml = "name: CI\njobs:\n  build:\n    runs-on: ubuntu-latest\n"

        script = renderer.render_script(
            workdir="/work",
            main_command='act --workflows "$SLURM_CI_WORKFLOW"',
            workflow_content=workflow_yaml,
        )

        assert "SLURM_CI_WORKFLOW=$(mktemp" in script
        assert "SLURM_CI_WORKFLOW_EOF" in script
        assert "name: CI" in script
        assert 'rm -f "$SLURM_CI_WORKFLOW"' in script

    def test_template_without_workflow_content_omits_heredoc(self) -> None:
        """Test that no heredoc block appears when workflow_content is None."""
        renderer = SlurmTemplateRenderer()

        script = renderer.render_script(
            workdir="/work",
            main_command="echo test",
        )

        assert "SLURM_CI_WORKFLOW" not in script
        assert "SLURM_CI_WORKFLOW_EOF" not in script


class TestBuildActCommand:
    """Tests for build_act_command function."""

    def test_basic_command(self) -> None:
        """Test building basic act command."""
        cmd = build_act_command(
            workflow_file="/path/to/workflow.yml",
            combo={"python-version": "3.9", "os": "ubuntu-latest"},
        )

        assert "--workflows /path/to/workflow.yml" in cmd
        assert "--matrix python-version:3.9" in cmd
        assert "--matrix os:ubuntu-latest" in cmd
        assert "--rm" in cmd
        assert "--dryrun" not in cmd

    def test_dryrun_command(self) -> None:
        """Test building act command with dryrun flag."""
        cmd = build_act_command(
            workflow_file="/path/to/workflow.yml",
            combo={"version": "1.0"},
            dryrun=True,
        )

        assert "--dryrun" in cmd


class TestGetDefaultSbatchOptions:
    """Tests for get_default_sbatch_options function."""

    def test_default_options(self) -> None:
        """Test getting default sbatch options."""
        options = get_default_sbatch_options(
            combo={"python-version": "3.9"},
            task_name="test-job",
            logfile_path="/path/to/log.txt",
        )

        assert options["job-name"] == "test-job"
        assert options["output"] == "/path/to/log.txt"
        assert "time" in options
        assert "cpus-per-task" in options


@patch("slurm_ci.slurm_launcher.subprocess.run")
@patch("slurm_ci.status_file.subprocess.check_output")
class TestLaunchSlurmJobs:
    """Tests for launch_slurm_jobs function with mocked subprocess."""

    def test_launch_basic(
        self,
        mock_check_output: Mock,
        mock_run: Mock,
        sample_workflow_file: Path,
        working_directory: Path,
    ) -> None:
        """Test basic job launching with mocked sbatch."""

        # Mock git commands for StatusFile - need multiple sets for matrix combinations
        def git_mock_side_effect(cmd, *args, **kwargs):
            if (
                "rev-parse" in cmd
                and "HEAD" in cmd
                and "--abbrev-ref" not in cmd
                and "--show-toplevel" not in cmd
            ):
                return b"abc123\n"
            elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                return b"/tmp/sample_project\n"
            elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return b"main\n"
            return b""

        mock_check_output.side_effect = git_mock_side_effect

        # Capture the script content before the temp file is cleaned up
        captured_scripts: list[str] = []

        def sbatch_side_effect(cmd, *args, **kwargs):
            with open(cmd[1]) as f:
                captured_scripts.append(f.read())
            return Mock(returncode=0, stdout="Submitted batch job 12345\n", stderr="")

        mock_run.side_effect = sbatch_side_effect

        launch_slurm_jobs(
            str(sample_workflow_file),
            str(working_directory),
            dryrun=False,
        )

        # Verify sbatch was called
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "sbatch"

        # Verify the generated script embeds the workflow content
        assert captured_scripts
        assert "SLURM_CI_WORKFLOW=$(mktemp" in captured_scripts[0]
        assert "Test Workflow" in captured_scripts[0]
        assert '"$SLURM_CI_WORKFLOW"' in captured_scripts[0]

    def test_launch_captures_workflow_content(
        self,
        mock_check_output: Mock,
        mock_run: Mock,
        sample_workflow_file: Path,
        working_directory: Path,
    ) -> None:
        """Launching a job stores workflow_content in the status TOML."""

        def git_mock_side_effect(cmd, *args, **kwargs):
            if (
                "rev-parse" in cmd
                and "HEAD" in cmd
                and "--abbrev-ref" not in cmd
                and "--show-toplevel" not in cmd
            ):
                return b"abc123\n"
            elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                return b"/tmp/sample_project\n"
            elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return b"main\n"
            return b""

        mock_check_output.side_effect = git_mock_side_effect
        mock_run.return_value = Mock(
            returncode=0, stdout="Submitted batch job 12345\n", stderr=""
        )

        launch_slurm_jobs(
            str(sample_workflow_file),
            str(working_directory),
            dryrun=False,
        )

        # Read back one of the status files and confirm workflow_content is set.
        import toml

        from slurm_ci.config import STATUS_DIR

        status_files = list(Path(STATUS_DIR).glob("*.toml"))
        assert status_files, "Expected at least one status file"
        data = toml.load(status_files[0])
        assert "workflow_content" in data["project"]
        assert "Test Workflow" in data["project"]["workflow_content"]

    def test_launch_with_custom_options(
        self,
        mock_check_output: Mock,
        mock_run: Mock,
        sample_workflow_file: Path,
        working_directory: Path,
    ) -> None:
        """Test launching with custom sbatch options."""

        def git_mock_side_effect(cmd, *args, **kwargs):
            if (
                "rev-parse" in cmd
                and "HEAD" in cmd
                and "--abbrev-ref" not in cmd
                and "--show-toplevel" not in cmd
            ):
                return b"abc123\n"
            elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                return b"/tmp/sample_project\n"
            elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return b"main\n"
            return b""

        mock_check_output.side_effect = git_mock_side_effect
        mock_run.return_value = Mock(
            returncode=0, stdout="Submitted batch job 99999\n", stderr=""
        )

        custom_options = {"partition": "gpu", "time": "02:00:00"}

        launch_slurm_jobs(
            str(sample_workflow_file),
            str(working_directory),
            custom_sbatch_options=custom_options,
        )

        assert mock_run.called

    def test_launch_with_matrix_map(
        self,
        mock_check_output: Mock,
        mock_run: Mock,
        sample_workflow_file: Path,
        working_directory: Path,
    ) -> None:
        """Test launching with matrix mapping."""

        def git_mock_side_effect(cmd, *args, **kwargs):
            if (
                "rev-parse" in cmd
                and "HEAD" in cmd
                and "--abbrev-ref" not in cmd
                and "--show-toplevel" not in cmd
            ):
                return b"abc123\n"
            elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                return b"/tmp/sample_project\n"
            elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return b"main\n"
            return b""

        mock_check_output.side_effect = git_mock_side_effect
        mock_run.return_value = Mock(
            returncode=0, stdout="Submitted batch job 99999\n", stderr=""
        )

        matrix_map = {
            "python-version": {
                "key": "partition",
                "value_prefix": "python-",
                "value_suffix": "",
            }
        }

        launch_slurm_jobs(
            str(sample_workflow_file),
            str(working_directory),
            matrix_map=matrix_map,
        )

        assert mock_run.called

    def test_launch_with_git_repo(
        self,
        mock_check_output: Mock,
        mock_run: Mock,
        sample_workflow_file: Path,
        working_directory: Path,
    ) -> None:
        """Test launching with git repository info."""

        def git_mock_side_effect(cmd, *args, **kwargs):
            if "ls-remote" in cmd:
                return b"abc123\tHEAD\n"
            return b""

        mock_check_output.side_effect = git_mock_side_effect
        mock_run.return_value = Mock(
            returncode=0, stdout="Submitted batch job 99999\n", stderr=""
        )

        git_repo = {
            "url": "https://github.com/user/repo",
            "branch": "main",
            "commit_sha": "abc123",
        }

        launch_slurm_jobs(
            str(sample_workflow_file),
            str(working_directory),
            git_repo=git_repo,
            git_repo_url="https://github.com/user/repo",
            git_repo_branch="main",
        )

        assert mock_run.called


@patch("slurm_ci.slurm_launcher.subprocess.run")
@patch("slurm_ci.status_file.subprocess.check_output")
class TestRelaunchSlurmJob:
    """Tests for relaunch_slurm_job function with mocked subprocess."""

    def test_relaunch_basic(
        self,
        mock_check_output: Mock,
        mock_run: Mock,
        tmp_path: Path,
    ) -> None:
        """Test basic job relaunching."""

        # Mock git commands
        def git_mock_side_effect(cmd, *args, **kwargs):
            if (
                "rev-parse" in cmd
                and "HEAD" in cmd
                and "--abbrev-ref" not in cmd
                and "--show-toplevel" not in cmd
            ):
                return b"abc123\n"
            elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                return b"/tmp/test_project\n"
            elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return b"main\n"
            return b""

        mock_check_output.side_effect = git_mock_side_effect

        # Create a status file
        workflow_file = tmp_path / "workflow.yml"
        workflow_file.write_text("name: test\njobs:\n  test:\n    runs-on: ubuntu")

        status_file = StatusFile(
            workflow_file=str(workflow_file),
            working_directory=str(tmp_path),
            matrix_args={"version": "1.0"},
        )
        status_file.write()

        # Mock sbatch
        mock_run.return_value = Mock(
            returncode=0, stdout="Submitted batch job 12345\n", stderr=""
        )

        relaunch_slurm_job(status_file)

        # Verify sbatch was called
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "sbatch"

    def test_relaunch_after_workflow_file_deleted(
        self,
        mock_check_output: Mock,
        mock_run: Mock,
        tmp_path: Path,
    ) -> None:
        """Relaunch succeeds using captured workflow_content even if the
        original workflow file no longer exists on disk."""

        workflow_yaml = "name: test\njobs:\n  test:\n    runs-on: ubuntu"

        def git_mock_side_effect(cmd, *args, **kwargs):
            if (
                "rev-parse" in cmd
                and "HEAD" in cmd
                and "--abbrev-ref" not in cmd
                and "--show-toplevel" not in cmd
            ):
                return b"abc123\n"
            elif "rev-parse" in cmd and "--show-toplevel" in cmd:
                return b"/tmp/test_project\n"
            elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return b"main\n"
            return b""

        mock_check_output.side_effect = git_mock_side_effect

        captured_scripts: list[str] = []

        def sbatch_side_effect(cmd, *args, **kwargs):
            with open(cmd[1]) as f:
                captured_scripts.append(f.read())
            return Mock(returncode=0, stdout="Submitted batch job 12345\n", stderr="")

        mock_run.side_effect = sbatch_side_effect

        # Create a workflow file and a status file that already stores the
        # workflow content (simulating a previous launch that captured it).
        workflow_file = tmp_path / "workflow.yml"
        workflow_file.write_text(workflow_yaml)

        status_file = StatusFile(
            workflow_file=str(workflow_file),
            working_directory=str(tmp_path),
            matrix_args={"version": "1.0"},
        )
        status_file.data["project"]["workflow_content"] = workflow_yaml
        status_file.write()

        # Delete the workflow file to simulate it being moved/removed.
        workflow_file.unlink()
        assert not workflow_file.exists()

        relaunch_slurm_job(status_file)

        assert mock_run.called
        assert captured_scripts
        assert "name: test" in captured_scripts[0]
